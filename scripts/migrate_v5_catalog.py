"""Explicitly migrate catalog rows into an empty v5 database; v4 stays read-only."""
from pathlib import Path
import argparse
from price_monitor_v5.catalog import CatalogStore

parser=argparse.ArgumentParser()
parser.add_argument("v4_database",type=Path)
parser.add_argument("v5_database",type=Path)
args=parser.parse_args()
count=CatalogStore(args.v5_database).import_v4_catalog(args.v4_database)
print(f"Copied {count} catalog rows. Old prices, history and retailer links were not migrated.")
