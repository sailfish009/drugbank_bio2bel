# -*- coding: utf-8 -*-

"""Constants for Bio2BEL DrugBank."""

import os

from bio2bel.utils import get_connection, get_data_dir

VERSION = '0.1.2-dev'

MODULE_NAME = 'drugbank'
DATA_DIR = get_data_dir(MODULE_NAME)

DRUGBANK_URL = 'https://www.drugbank.ca/releases/5-1-4/downloads/all-full-database'
DRUGBANK_PATH = os.path.join(DATA_DIR, 'drugbank_all_full_database.xml.zip')
