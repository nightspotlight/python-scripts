#!/usr/bin/env python3

"""a script to delete releases older than specified version for each artifact in a group id from Sonatype Nexus 2"""

import argparse
import os
from distutils.version import LooseVersion

import requests
from requests.auth import HTTPBasicAuth

USERNAME = str(os.environ.get('NEXUS_USERNAME'))
PASSWORD = str(os.environ.get('NEXUS_PASSWORD'))
AUTH = HTTPBasicAuth(USERNAME, PASSWORD)
HEADERS = {'Accept': 'application/json'}
NEXUS_URL = 'https://nexus.company.com'
NEXUS_REPO = 'releases'
CONTENT_URL = f'{NEXUS_URL}/service/local/repositories/{NEXUS_REPO}/content'
METADATA_URL = f'{NEXUS_URL}/service/local/metadata/repositories/{NEXUS_REPO}/content'
INDEX_URL = f'{NEXUS_URL}/service/local/data_incremental_index/repositories/{NEXUS_REPO}/content'

argparser = argparse.ArgumentParser()
argparser.add_argument('group_id',
                       help='group id in Maven notation to query for artifacts; example: com.company.project')
argparser.add_argument('version',
                       help='release versions less or equal than this version will be deleted; example: 1.2.3')
argparser.add_argument('-n', '--dry-run',
                       action='store_true',
                       help='only retrieve data, do not modify or delete anything')
args = argparser.parse_args()

path = args.group_id.replace('.', '/')
version = args.version

response = requests.get(f'{CONTENT_URL}/{path}', headers=HEADERS, auth=AUTH, timeout=10.0)
if response.status_code not in [200, 204]: response.raise_for_status()

output = response.json().get('data')

if not output:
    print(f'No valid resources found at {response.url}')
    raise SystemExit

artifacts_to_rm = {resource.get('text'): []
                   for resource in output
                   if resource.get('leaf') is False}

for resource in output:
    artifact = resource.get('text')

    response = requests.get(resource.get('resourceURI'), headers=HEADERS, auth=AUTH, timeout=10.0)
    if response.status_code not in [200, 204]: response.raise_for_status()

    output = response.json().get('data')

    artifacts_to_rm[artifact] = sorted(
        list(
            resource.get('resourceURI')
            for resource in output
            if resource.get('leaf') is False
            and LooseVersion(resource.get('text')) <= LooseVersion(version)
        ),
        key=lambda v: LooseVersion(v)
    )

print(f'Cleaning up artifacts for {args.group_id}, deleting release versions <={version}.')
for artifact, urls in artifacts_to_rm.items():
    if not urls:
        print(f'Nothing to delete for {artifact}.')
        continue

    print(f'{artifact}:')
    for url in urls:
        if args.dry_run:
            print(f' - would delete {url}')
        else:
            print(f' - deleting {url}')
            response = requests.delete(url, auth=AUTH, timeout=10.0)
            if response.status_code not in [200, 204]: response.raise_for_status()

    if args.dry_run:
        print(f'Would request to rebuilt metadata for {artifact}.')
    else:
        print(f'Requesting to rebuild metadata for {artifact}.')
        response = requests.delete(f'{METADATA_URL}/{path}/{artifact}', auth=AUTH, timeout=10.0)
        if response.status_code not in [200, 204]: response.raise_for_status()

    if args.dry_run:
        print(f'Would request to update index for {artifact}.')
    else:
        print(f'Requesting to update index for {artifact}.')
        response = requests.delete(f'{INDEX_URL}/{path}/{artifact}', auth=AUTH, timeout=10.0)
        if response.status_code not in [200, 204]: response.raise_for_status()

print('All ok!')
