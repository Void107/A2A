"""Offline publication precheck; never activates a contract or grants access."""
import argparse
import json
import sys
from pathlib import Path

from .loader import ContractInvalid, contract_digest, load_contract


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('contract', type=Path)
    args = parser.parse_args()
    try:
        # Bound before parsing, including when the caller supplies a large file.
        with args.contract.open('rb') as stream:
            contract = load_contract(stream.read(262145))
        print(json.dumps({'status': 'validated', 'contract_id': contract['contract_id'],
                          'contract_version': contract['contract_version'],
                          'digest': contract_digest(contract)}))
        return 0
    except (ContractInvalid, OSError) as error:
        print(json.dumps({'status': 'invalid', 'code': 'CONTRACT_INVALID',
                          'rule': getattr(error, 'rule', 'file_unavailable')}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
