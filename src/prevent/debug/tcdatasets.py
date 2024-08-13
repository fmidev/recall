"""List terracotta datasets."""
import os

import terracotta as tc

DB_URI = os.environ.get('TC_DB_URI', 'postgresql://postgres:postgres@localhost:5432/terracotta')


if __name__ == '__main__':
    driver = tc.get_driver(DB_URI)
    print(driver.get_datasets())