# -*- coding: utf-8 -*-

"""Parsers for Bio2BEL DrugBank."""

import itertools as itt
import logging
import os
import re
import sys
import time
import zipfile
from datetime import datetime
from typing import Mapping, Optional
from xml.etree import ElementTree

from tqdm import tqdm

from bio2bel_drugbank.constants import DRUGBANK_PATH

log = logging.getLogger(__name__)

ns = '{http://www.drugbank.ca}'
inchikey_template = f"{ns}calculated-properties/{ns}property[{ns}kind='InChIKey']/{ns}value"
inchi_template = f"{ns}calculated-properties/{ns}property[{ns}kind='InChI']/{ns}value"
smiles_template = f"{ns}calculated-properties/{ns}property[{ns}kind='SMILES']/{ns}value"

pubmed_re = re.compile('pubmed/([0-9]+)')


def get_path(path: Optional[str] = None) -> str:
    """Get the path to the DrugBank data."""
    if path is not None:
        return path

    if os.path.exists(DRUGBANK_PATH):
        return DRUGBANK_PATH

    log.critical("""DrugBank data not found.

Unfortunately, the data for DrugBank is not available via an open HTTP(S) or FTP endpoint, so please follow these 
steps to get it yourself:

1. Make an account at: https://www.drugbank.ca
2. Navigate to: https://www.drugbank.ca/releases/5-1-1/downloads/all-full-database
3. Unzip the file that gets downloaded. There should be an XML called "full database.xml"
4. Run the following command on the command line: `mkdir -p ~/.bio2bel/drugbank`. If you're specifying the Bio2BEL
   directory through a config file or an environment variable, just make a "drugbank" folder there.
5. Copy "full database.xml" into this folder.
6. Resume business as usual (try `bio2bel_drugbank populate` now)""")
    sys.exit(0)


def get_xml_root(path: Optional[str] = None) -> ElementTree.Element:
    """Get the XML parser root.

    Takes between 35-60 seconds.

    :param path: A custom URL for DrugBank XML file
    """
    path = get_path(path=path)
    log.info('parsing drugbank at %s', path)
    t = time.time()

    if path.endswith('.xml'):
        tree = ElementTree.parse(path)
    elif path.endswith('.zip'):
        with zipfile.ZipFile(path) as z:
            with z.open('full database.xml') as f:
                tree = ElementTree.parse(f)
    else:
        raise ValueError

    log.info('parsed drugbank in %.2f seconds', time.time() - t)

    return tree.getroot()


def extract_drug_info(drug_xml: ElementTree.Element):
    """Extract information from an XML element representing a drug."""
    assert drug_xml.tag == f'{ns}drug'

    row = {
        'type': drug_xml.get('type'),
        'drugbank_id': drug_xml.findtext(f"{ns}drugbank-id[@primary='true']"),
        'cas_number': drug_xml.findtext(f"{ns}cas-number"),
        'name': drug_xml.findtext(f"{ns}name"),
        'description': drug_xml.findtext(f"{ns}description"),
        'groups': [
            group.text
            for group in drug_xml.findall(f"{ns}groups/{ns}group")
        ],
        'atc_codes': [
            code.get('code')
            for code in drug_xml.findall(f"{ns}atc-codes/{ns}atc-code")
        ],
        'categories': [
            {
                'name': x.findtext(f'{ns}category'),
                'mesh_id': x.findtext(f'{ns}mesh-id'),
            }
            for x in drug_xml.findall(f"{ns}categories/{ns}category")
        ],
        'patents': [
            {
                'patent_id': x.findtext(f'{ns}number'),
                'country': x.findtext(f'{ns}country'),
                'approved': datetime.strptime(x.findtext(f'{ns}approved'), '%Y-%m-%d'),
                'expires': datetime.strptime(x.findtext(f'{ns}expires'), '%Y-%m-%d'),
                'pediatric_extension': x.findtext(f'{ns}pediatric-extension') != 'false',

            }
            for x in drug_xml.findall(f"{ns}patents/{ns}patent")
        ],
        'xrefs': [
            {
                'resource': x.findtext(f'{ns}resource'),
                'identifier': x.findtext(f'{ns}identifier'),
            }
            for x in drug_xml.findall(f"{ns}external-identifiers/{ns}external-identifier")
        ],
        'inchi': drug_xml.findtext(inchi_template),
        'inchikey': drug_xml.findtext(inchikey_template),
        'smiles': drug_xml.findtext(smiles_template),
    }

    # Add drug aliases
    aliases = {
        elem.text.strip() for elem in
        itt.chain(
            drug_xml.findall(f"{ns}international-brands/{ns}international-brand"),
            drug_xml.findall(f"{ns}synonyms/{ns}synonym[@language='English']"),
            drug_xml.findall(f"{ns}international-brands/{ns}international-brand"),
            drug_xml.findall(f"{ns}products/{ns}product/{ns}name"),
        )
        if elem.text.strip()
    }
    aliases.add(row['name'])
    row['aliases'] = aliases

    row['protein_interactions'] = []
    row['protein_group_interactions'] = []

    for category, protein in _iterate_protein_stuff(drug_xml):
        target_row = extract_protein_info(category, protein)
        if not target_row:
            continue
        row['protein_interactions'].append(target_row)

    return row


_categories = ['target', 'enzyme', 'carrier', 'transporter']


def _iterate_protein_stuff(drug_xml):
    """

    :param drug_xml:
    :return: iterates over pairs of category and protein xml
    """
    for category in _categories:
        proteins = drug_xml.findall(f'{ns}{category}s/{ns}{category}')
        for protein in proteins:
            yield category, protein


def extract_protein_info(category, protein):
    # FIXME Differentiate between proteins and protein groups/complexes
    polypeptides = protein.findall(f'{ns}polypeptide')

    if len(polypeptides) == 0:
        protein_type = 'none'
    elif len(polypeptides) == 1:
        protein_type = 'single'
    else:
        protein_type = 'group'

    row = {
        'target': {
            'type': protein_type,
            'category': category,
            'known_action': protein.findtext(f'{ns}known-action'),
            'name': protein.findtext(f'{ns}name'),
            'actions': [
                action.text
                for action in protein.findall(f'{ns}actions/{ns}action')
            ],
            'articles': [
                pubmed_element.text
                for pubmed_element in protein.findall(f'{ns}references/{ns}articles/{ns}article/{ns}pubmed-id')
                if pubmed_element.text
            ],
        },
        'polypeptides': [
            {
                'name': polypeptide.findtext(f'{ns}name'),
                'hgnc_symbol': polypeptide.findtext(f'{ns}gene-name'),
                'hgnc_id': polypeptide.findtext(
                    f"{ns}external-identifiers/{ns}external-identifier[{ns}resource='HUGO Gene Nomenclature Committee (HGNC)']/{ns}identifier",
                )[len('HGNC:'):],
                'uniprot_id': polypeptide.findtext(
                    f"{ns}external-identifiers/{ns}external-identifier[{ns}resource='UniProtKB']/{ns}identifier",
                ),
                'uniprot_accession': polypeptide.findtext(
                    f"{ns}external-identifiers/{ns}external-identifier[{ns}resource='UniProt Accession']/{ns}identifier",
                ),
                'organism': polypeptide.findtext(f'{ns}organism'),
                'taxonomy': polypeptide.find(f'{ns}organism').attrib['ncbi-taxonomy-id'],
            }
            for polypeptide in polypeptides
        ],
    }

    return row


def get_pubchem_to_drugbank(path=None) -> Mapping[str, str]:
    """Get a mapping from PubChem Substances to DrugBank identifiers."""
    rv = {}
    root = get_xml_root(path=path)
    for drug_xml in tqdm(root, desc='Drugs'):
        drug = extract_drug_info(drug_xml)
        drugbank_id = drug['drugbank_id']
        for xref in drug['xrefs']:
            if xref['resource'] == 'PubChem Substance':
                rv[xref['identifier']] = drugbank_id
                break
        else:
            print(f'could not find pubchem for {drugbank_id}')

    return rv


def main():
    x = get_pubchem_to_drugbank('/Users/cthoyt/.bio2bel/drugbank/test.xml')
    import json

    with open('/Users/cthoyt/Desktop/pubchem_to_drugbank.json', 'w') as f:
        json.dump(x, f)


if __name__ == '__main__':
    main()
