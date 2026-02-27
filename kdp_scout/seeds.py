"""Seed keyword manager for automated re-mining.

Tracks seed keywords used for mining so automation can re-mine them
on a schedule. Seeds are persisted to a JSON file in the data/ directory.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from kdp_scout.config import Config

logger = logging.getLogger(__name__)

# Default seeds file location (relative to project root)
_project_root = Path(__file__).parent.parent
DEFAULT_SEEDS_FILE = _project_root / 'data' / 'seeds.json'


class SeedManager:
    """Manage seed keywords for automated re-mining.

    Seeds are stored as a JSON file with keyword text, department,
    and metadata about when they were added and last mined.
    """

    def __init__(self, seeds_file=None):
        """Initialize the seed manager.

        Args:
            seeds_file: Path to the seeds JSON file.
                        Defaults to data/seeds.json in the project root.
        """
        self.seeds_file = Path(seeds_file) if seeds_file else DEFAULT_SEEDS_FILE
        self._seeds = []
        self.load()

    def add_seed(self, keyword, department='kindle'):
        """Add a seed keyword to the persistent list.

        If the keyword already exists (case-insensitive), updates its
        department and last_added timestamp.

        Args:
            keyword: The seed keyword text.
            department: Amazon department ('kindle', 'books', 'all').

        Returns:
            True if the seed was newly added, False if updated.
        """
        keyword_lower = keyword.lower().strip()
        if not keyword_lower:
            return False

        # Check for existing seed
        for seed in self._seeds:
            if seed['keyword'] == keyword_lower:
                seed['department'] = department
                seed['last_added'] = datetime.now().isoformat()
                self.save()
                logger.info(f'Updated seed keyword: "{keyword_lower}"')
                return False

        # Add new seed
        self._seeds.append({
            'keyword': keyword_lower,
            'department': department,
            'added_at': datetime.now().isoformat(),
            'last_added': datetime.now().isoformat(),
            'last_mined': None,
            'mine_count': 0,
        })
        self.save()
        logger.info(f'Added seed keyword: "{keyword_lower}" ({department})')
        return True

    def remove_seed(self, keyword):
        """Remove a seed keyword.

        Args:
            keyword: The seed keyword text to remove.

        Returns:
            True if removed, False if not found.
        """
        keyword_lower = keyword.lower().strip()
        original_count = len(self._seeds)
        self._seeds = [
            s for s in self._seeds if s['keyword'] != keyword_lower
        ]
        if len(self._seeds) < original_count:
            self.save()
            logger.info(f'Removed seed keyword: "{keyword_lower}"')
            return True
        return False

    def mark_mined(self, keyword):
        """Mark a seed as having been mined.

        Updates the last_mined timestamp and increments mine_count.

        Args:
            keyword: The seed keyword text.
        """
        keyword_lower = keyword.lower().strip()
        for seed in self._seeds:
            if seed['keyword'] == keyword_lower:
                seed['last_mined'] = datetime.now().isoformat()
                seed['mine_count'] = seed.get('mine_count', 0) + 1
                self.save()
                return

    def list_seeds(self):
        """Get all seed keywords.

        Returns:
            List of seed dicts with keys: keyword, department, added_at,
            last_added, last_mined, mine_count.
        """
        return list(self._seeds)

    def get_seeds_for_mining(self, department=None):
        """Get seed keywords filtered for mining.

        Args:
            department: Optional department filter.

        Returns:
            List of (keyword, department) tuples.
        """
        results = []
        for seed in self._seeds:
            if department and seed['department'] != department:
                continue
            results.append((seed['keyword'], seed['department']))
        return results

    def save(self):
        """Persist seeds to JSON file."""
        # Ensure directory exists
        self.seeds_file.parent.mkdir(parents=True, exist_ok=True)

        with open(self.seeds_file, 'w') as f:
            json.dump({
                'seeds': self._seeds,
                'last_updated': datetime.now().isoformat(),
                'version': 1,
            }, f, indent=2)

        logger.debug(f'Saved {len(self._seeds)} seeds to {self.seeds_file}')

    def load(self):
        """Load seeds from JSON file.

        If the file doesn't exist, starts with an empty seed list.
        """
        if not self.seeds_file.exists():
            self._seeds = []
            logger.debug(f'No seeds file found at {self.seeds_file}')
            return

        try:
            with open(self.seeds_file, 'r') as f:
                data = json.load(f)
            self._seeds = data.get('seeds', [])
            logger.debug(f'Loaded {len(self._seeds)} seeds from {self.seeds_file}')
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f'Failed to load seeds file: {e}')
            self._seeds = []

    def __len__(self):
        return len(self._seeds)

    def __repr__(self):
        return f'SeedManager({len(self._seeds)} seeds)'
