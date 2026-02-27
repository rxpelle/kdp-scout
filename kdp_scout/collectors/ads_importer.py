"""Amazon Ads search term report importer.

Parses Amazon Ads bulk report CSV files exported from the advertising
console. Supports common column name variations and metadata header rows.

Imported data is stored in ads_search_terms and cross-referenced with
the keywords table to enrich keyword metrics with real ads performance data.
"""

import logging
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from kdp_scout.db import AdsRepository, KeywordRepository, init_db

logger = logging.getLogger(__name__)

# Column name mappings: canonical name -> list of possible column names (lowercase)
COLUMN_ALIASES = {
    'campaign_name': ['campaign name', 'campaign'],
    'ad_group': ['ad group name', 'ad group', 'adgroup'],
    'search_term': [
        'customer search term', 'search term', 'query',
        'search query', 'keyword',
    ],
    'match_type': ['match type', 'keyword match type', 'targeting type'],
    'impressions': ['impressions', 'impr', 'impr.'],
    'clicks': ['clicks'],
    'ctr': ['click-thru rate (ctr)', 'ctr', 'click-through rate', 'click thru rate'],
    'cpc': ['cost per click (cpc)', 'cpc', 'avg. cpc', 'avg cpc'],
    'spend': ['spend', 'cost', 'total spend'],
    'sales': [
        '7 day total sales', 'total sales', 'sales',
        '7 day total sales (#)', '14 day total sales',
    ],
    'acos': [
        'total advertising cost of sales (acos)', 'acos',
        'total advertising cost of sales',
    ],
    'orders': [
        '7 day total orders (#)', '7 day total orders', 'total orders',
        'orders', '14 day total orders',
    ],
    'units': [
        '7 day total units (#)', '7 day total units', 'total units',
        'units', '14 day total units',
    ],
}


class AdsImporter:
    """Imports Amazon Ads search term report CSVs into the database."""

    def __init__(self):
        """Initialize with database connections."""
        init_db()
        self._ads_repo = AdsRepository()
        self._kw_repo = KeywordRepository()

    def close(self):
        """Close database connections."""
        self._ads_repo.close()
        self._kw_repo.close()

    def import_csv(self, filepath: str, campaign_filter: str = None) -> dict:
        """Import Amazon Ads search term report.

        Handles common CSV format variations:
        - Metadata rows before the header
        - Different column naming conventions
        - Percentage values with % signs
        - Currency values with $ signs

        Args:
            filepath: Path to the CSV file.
            campaign_filter: Optional campaign name to filter by.

        Returns:
            dict with 'imported', 'skipped', 'keywords_enriched' counts.
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f'File not found: {filepath}')

        logger.info(f'Importing ads report: {filepath}')

        # Read CSV, handling metadata rows at top
        df = self._read_csv_flexible(filepath)

        if df is None or df.empty:
            logger.warning('No data found in CSV file')
            return {'imported': 0, 'skipped': 0, 'keywords_enriched': 0}

        # Map columns to canonical names
        column_map = self._map_columns(df.columns.tolist())

        if 'search_term' not in column_map:
            raise ValueError(
                'Could not find a search term column in the CSV. '
                f'Found columns: {list(df.columns)}'
            )

        # Apply campaign filter if specified
        if campaign_filter and 'campaign_name' in column_map:
            camp_col = column_map['campaign_name']
            df = df[df[camp_col].str.contains(campaign_filter, case=False, na=False)]
            if df.empty:
                logger.warning(f'No rows match campaign filter: {campaign_filter}')
                return {'imported': 0, 'skipped': 0, 'keywords_enriched': 0}

        imported = 0
        skipped = 0
        keywords_enriched = 0
        now = datetime.now().isoformat()
        today = datetime.now().strftime('%Y-%m-%d')

        for _, row in df.iterrows():
            search_term = self._get_value(row, column_map, 'search_term')
            if not search_term or not isinstance(search_term, str):
                skipped += 1
                continue

            search_term = search_term.strip().lower()
            if not search_term or search_term == '*':
                skipped += 1
                continue

            # Parse numeric values
            impressions = self._parse_int(
                self._get_value(row, column_map, 'impressions')
            )
            clicks = self._parse_int(
                self._get_value(row, column_map, 'clicks')
            )
            ctr = self._parse_percentage(
                self._get_value(row, column_map, 'ctr')
            )
            spend = self._parse_currency(
                self._get_value(row, column_map, 'spend')
            )
            sales = self._parse_currency(
                self._get_value(row, column_map, 'sales')
            )
            acos = self._parse_percentage(
                self._get_value(row, column_map, 'acos')
            )
            orders = self._parse_int(
                self._get_value(row, column_map, 'orders')
            )
            campaign_name = self._get_value(row, column_map, 'campaign_name')
            ad_group = self._get_value(row, column_map, 'ad_group')
            match_type = self._get_value(row, column_map, 'match_type')

            # Store in ads_search_terms table
            try:
                self._ads_repo.add_search_term(
                    campaign_name=campaign_name,
                    ad_group=ad_group,
                    search_term=search_term,
                    keyword_match_type=match_type,
                    impressions=impressions,
                    clicks=clicks,
                    ctr=ctr,
                    spend=spend,
                    sales=sales,
                    acos=acos,
                    orders=orders,
                    report_date=today,
                    imported_at=now,
                )
                imported += 1

                # Cross-reference with keywords table
                keyword_id, is_new = self._kw_repo.upsert_keyword(
                    search_term, source='ads_report'
                )

                # Enrich keyword_metrics with ads data
                if impressions or clicks or orders:
                    self._kw_repo.add_metric(
                        keyword_id,
                        impressions=impressions,
                        clicks=clicks,
                        orders=orders,
                    )
                    keywords_enriched += 1

            except Exception as e:
                logger.error(
                    f'Database error importing search term "{search_term}": {e}'
                )
                skipped += 1

        result = {
            'imported': imported,
            'skipped': skipped,
            'keywords_enriched': keywords_enriched,
        }
        logger.info(
            f'Import complete: {imported} imported, {skipped} skipped, '
            f'{keywords_enriched} keywords enriched'
        )
        return result

    def _read_csv_flexible(self, filepath):
        """Read a CSV file, handling metadata rows before the header.

        Amazon sometimes prepends metadata rows (campaign info, date ranges)
        before the actual header row. This method detects the header by
        looking for rows containing known column names.

        Args:
            filepath: Path to CSV file.

        Returns:
            pandas DataFrame or None.
        """
        # First, try reading normally
        try:
            df = pd.read_csv(filepath, dtype=str)
            # Check if first row columns look like a valid header
            cols_lower = [str(c).lower().strip() for c in df.columns]
            if self._looks_like_header(cols_lower):
                return df
        except Exception:
            pass

        # Try skipping rows until we find the header
        try:
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            with open(filepath, 'r', encoding='latin-1') as f:
                lines = f.readlines()

        for skip_rows in range(min(10, len(lines))):
            try:
                df = pd.read_csv(filepath, skiprows=skip_rows, dtype=str)
                cols_lower = [str(c).lower().strip() for c in df.columns]
                if self._looks_like_header(cols_lower):
                    return df
            except Exception:
                continue

        logger.error(f'Could not find a valid header row in {filepath}')
        return None

    def _looks_like_header(self, columns_lower):
        """Check if a list of column names looks like an ads report header.

        Args:
            columns_lower: List of lowercase column names.

        Returns:
            True if at least 3 known column names are found.
        """
        known_terms = set()
        for canonical, aliases in COLUMN_ALIASES.items():
            for alias in aliases:
                if alias in columns_lower:
                    known_terms.add(canonical)
                    break
        return len(known_terms) >= 3

    def _map_columns(self, columns):
        """Map CSV column names to canonical names.

        Args:
            columns: List of original column names from the CSV.

        Returns:
            Dict mapping canonical names to original column names.
        """
        column_map = {}
        cols_lower = {str(c).lower().strip(): c for c in columns}

        for canonical, aliases in COLUMN_ALIASES.items():
            for alias in aliases:
                if alias in cols_lower:
                    column_map[canonical] = cols_lower[alias]
                    break
            else:
                # Fuzzy match: look for columns containing the alias
                for alias in aliases:
                    for col_lower, col_original in cols_lower.items():
                        if alias in col_lower:
                            column_map[canonical] = col_original
                            break
                    if canonical in column_map:
                        break

        logger.debug(f'Column mapping: {column_map}')
        return column_map

    def _get_value(self, row, column_map, canonical_name):
        """Get a value from a row using the column mapping.

        Args:
            row: pandas Series (a row from the DataFrame).
            column_map: Dict mapping canonical names to column names.
            canonical_name: The canonical column name to look up.

        Returns:
            The value, or None if the column doesn't exist.
        """
        col = column_map.get(canonical_name)
        if col is None:
            return None
        val = row.get(col)
        if pd.isna(val):
            return None
        return val

    def _parse_int(self, value):
        """Parse an integer value, handling commas and whitespace.

        Args:
            value: String or numeric value.

        Returns:
            int or None.
        """
        if value is None:
            return None
        try:
            cleaned = str(value).replace(',', '').replace(' ', '').strip()
            if not cleaned or cleaned == '-':
                return None
            return int(float(cleaned))
        except (ValueError, TypeError):
            return None

    def _parse_percentage(self, value):
        """Parse a percentage value (e.g., '12.5%' or 0.125).

        Args:
            value: String or numeric value.

        Returns:
            float as a decimal (e.g., 0.125 for 12.5%) or None.
        """
        if value is None:
            return None
        try:
            cleaned = str(value).strip()
            if not cleaned or cleaned == '-':
                return None
            if '%' in cleaned:
                cleaned = cleaned.replace('%', '').strip()
                return float(cleaned) / 100.0
            val = float(cleaned)
            # If value > 1, assume it's already a percentage
            if val > 1:
                return val / 100.0
            return val
        except (ValueError, TypeError):
            return None

    def _parse_currency(self, value):
        """Parse a currency value (e.g., '$12.50' or '12.50').

        Args:
            value: String or numeric value.

        Returns:
            float or None.
        """
        if value is None:
            return None
        try:
            cleaned = str(value).replace('$', '').replace(',', '').strip()
            if not cleaned or cleaned == '-':
                return None
            return float(cleaned)
        except (ValueError, TypeError):
            return None
