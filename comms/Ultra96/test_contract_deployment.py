"""A standalone board deployment must not depend on a sibling Unity checkout."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import contract_validation


class ContractDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.source = Path(__file__).resolve().parents[1] / 'contracts'

    def test_board_layout_finds_bundled_schemas_without_environment_or_unity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / 'comms/contracts'
            shutil.copytree(self.source, bundle)
            script = root / 'comms/esp_ai_live/contract_validation.py'
            with patch.object(contract_validation, '__file__', str(script)), patch.dict(os.environ, {}, clear=True):
                self.assertEqual(contract_validation.contracts_directory(), bundle.resolve())

    def test_explicit_incomplete_directory_names_missing_files_and_does_not_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path/'client-hello.schema.json').write_text('{}')
            with self.assertRaises(RuntimeError) as result:
                contract_validation.contracts_directory(path)
            self.assertIn(str(path.resolve()), str(result.exception))
            self.assertIn('player-command.schema.json', str(result.exception))
            self.assertIn('match-state.schema.json', str(result.exception))

    def test_all_ten_schemas_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'contracts'
            shutil.copytree(self.source, path)
            (path/'game-event.schema.json').unlink()
            with self.assertRaisesRegex(RuntimeError, 'game-event.schema.json'):
                contract_validation.contracts_directory(path)
