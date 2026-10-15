#!/usr/bin/env python3
"""Run by an authorized AWS operator; never invoked by the Web/API handler."""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from passkeys import issue_grant, records, partition
from storage import Store


def main():
    parser = argparse.ArgumentParser(description='Operator-only Passkey authorization and recovery')
    commands = parser.add_subparsers(dest='operation', required=True)
    permission = commands.add_parser('grant')
    permission.add_argument('purpose', choices=['register', 'manage'])
    permission.add_argument('--origin', required=True, help='Exact production HTTPS origin, no trailing slash')
    commands.add_parser('list')
    commands.add_parser('clear-sessions', help='After stopping Passkey issuance and draining in-flight requests, delete only Passkey Sessions')
    revoke = commands.add_parser('revoke')
    revoke.add_argument('key', help='CRED# hash shown by list')
    args = parser.parse_args()
    store = Store()
    if args.operation == 'grant':
        from urllib.parse import urlsplit
        url = urlsplit(args.origin)
        if url.scheme != 'https' or url.netloc != url.hostname or url.path or url.query or url.fragment:
            parser.error('origin must be an exact HTTPS origin')
        # The only deliberate secret output; deliver privately, never paste into logs/URLs.
        print(issue_grant(store, args.purpose, time.time(), args.origin))
    elif args.operation == 'list':
        for row in records(store):
            print(row['sk'], row['label'], 'revoked' if 'revoked_at' in row else 'active')
    elif args.operation == 'clear-sessions':
        from boto3.dynamodb.conditions import Key
        from botocore.exceptions import ClientError
        from storage import is_condition_failure
        cursor, removed = None, 0
        while True:
            query = {'KeyConditionExpression': Key('pk').eq('AUTH#SESSION'), 'ConsistentRead': True}
            if cursor:
                query['ExclusiveStartKey'] = cursor
            page = store.table.query(**query)
            for session in page.get('Items', []):
                if session.get('credential_key'):
                    try:
                        store.table.delete_item(Key={'pk': session['pk'], 'sk': session['sk']},
                                                ConditionExpression='attribute_exists(credential_key)')
                        removed += 1
                    except ClientError as exc:
                        if not is_condition_failure(exc):
                            raise
            cursor = page.get('LastEvaluatedKey')
            if not cursor:
                break
        print(f'Removed {removed} Passkey Sessions; password Sessions unchanged.')
    else:
        import re
        if not re.fullmatch(r'CRED#[0-9a-f]{64}', args.key):
            parser.error('invalid credential key')
        store.table.update_item(Key={'pk': partition(store), 'sk': args.key},
                                UpdateExpression='SET revoked_at = :now',
                                ConditionExpression='attribute_exists(pk)',
                                ExpressionAttributeValues={':now': int(time.time())})
        print('Revoked; all synchronized copies and subsequent Session requests are rejected.')


if __name__ == '__main__':
    main()
