import unittest
import json
import yaml
import io
from unittest.mock import Mock
from .. import loader, amaxa
from ..__main__ import main as main


credentials_good_yaml = '''
version: 1
credentials:
    username: 'test@example.com'
    password: 'blah'
    security-token: '00000'
    sandbox: True
'''

credentials_good_json = '''
{
    "version": 1,
    "credentials": {
        "username": "test@example.com",
        "password": "blah",
        "security-token": "00000",
        "sandbox": true
    }
}
'''

credentials_bad = '''
credentials:
    username: 'test@example.com'
    password: 'blah'
    security-token: '00000'
    sandbox: True
'''

extraction_good_yaml = '''
version: 1
operation:
    - 
        sobject: Account
        fields: 
            - Name
            - Id
            - ParentId
        extract: 
            all: True
'''
extraction_good_json = '''
{
    "version": 1,
    "extraction": [
        {
            "sobject": "Account",
            "fields": [
                "Name",
                "Id",
                "ParentId"
            ],
            "extract": {
                "all": true
            }
        }
    ]
}
'''
extraction_bad = '''
operation:
    - 
        sobject: Account
        fields: 
            - Name
            - Id
            - ParentId
        extract: 
            all: True
'''

state_good_yaml = '''
version: 1
state:
    stage: inserts
    id-map:
        '001000000000001': '001000000000002'
        '001000000000003': '001000000000004'
'''

state_file = io.StringIO()

def select_file(f, *args, **kwargs):
    data = { 
        'credentials-bad.yaml': credentials_bad,
        'extraction-bad.yaml': extraction_bad,
        'extraction-good.yaml': extraction_good_yaml,
        'credentials-good.yaml': credentials_good_yaml,
        'credentials-good.json': credentials_good_json,
        'extraction-good.json': extraction_good_json,
        'state-good.yaml': state_good_yaml,
        'extraction-good.state.yaml': state_file
    }
    if type(data[f]) is str:
        m = unittest.mock.mock_open(read_data=data[f])(f, *args, **kwargs)
        m.name = f
    else:
        m = data[f]
    
    return m

class test_CLI(unittest.TestCase):
    @unittest.mock.patch('amaxa.__main__.loader.load_credentials')
    @unittest.mock.patch('amaxa.__main__.loader.load_extraction_operation')
    def test_main_calls_execute_with_json_input_extract_mode(self, extraction_mock, credential_mock):
        context = Mock()
        context.run.return_value = 0
        credential_mock.return_value = (context, [])
        extraction_mock.return_value = (context, [])
        
        m = Mock(side_effect=select_file)
        with unittest.mock.patch('builtins.open', m):
            with unittest.mock.patch(
                'sys.argv',
                ['amaxa', '-c', 'credentials-good.json', 'extraction-good.json']
            ):
                return_value = main()

        credential_mock.assert_called_once_with(json.loads(credentials_good_json), False)
        extraction_mock.assert_called_once_with(json.loads(extraction_good_json), context)

        extraction_mock.return_value[0].run.assert_called_once_with()

        self.assertEqual(0, return_value)
    
    @unittest.mock.patch('amaxa.__main__.loader.load_credentials')
    @unittest.mock.patch('amaxa.__main__.loader.load_load_operation')
    def test_main_calls_execute_with_json_input_load_mode(self, extraction_mock, credential_mock):
        context = Mock()
        context.run.return_value = 0
        credential_mock.return_value = (context, [])
        extraction_mock.return_value = (context, [])
        
        m = Mock(side_effect=select_file)
        with unittest.mock.patch('builtins.open', m):
            with unittest.mock.patch(
                'sys.argv',
                ['amaxa', '-c', 'credentials-good.json', '--load', 'extraction-good.json']
            ):
                return_value = main()

        credential_mock.assert_called_once_with(json.loads(credentials_good_json), True)
        extraction_mock.assert_called_once_with(json.loads(extraction_good_json), context, False)

        extraction_mock.return_value[0].run.assert_called_once_with()

        self.assertEqual(0, return_value)

    @unittest.mock.patch('amaxa.__main__.loader.load_credentials')
    @unittest.mock.patch('amaxa.__main__.loader.load_extraction_operation')
    def test_main_calls_execute_with_yaml_input(self, extraction_mock, credential_mock):
        context = Mock()
        context.run.return_value = 0
        credential_mock.return_value = (context, [])
        extraction_mock.return_value = (context, [])
        
        m = Mock(side_effect=select_file)
        with unittest.mock.patch('builtins.open', m):
            with unittest.mock.patch(
                'sys.argv',
                ['amaxa', '-c', 'credentials-good.yaml', 'extraction-good.yaml']
            ):
                return_value = main()

        credential_mock.assert_called_once_with(yaml.safe_load(credentials_good_yaml), False)
        extraction_mock.assert_called_once_with(yaml.safe_load(extraction_good_yaml), context)

        extraction_mock.return_value[0].run.assert_called_once_with()

        self.assertEqual(0, return_value)

    @unittest.mock.patch('amaxa.__main__.loader.load_credentials')
    @unittest.mock.patch('amaxa.__main__.loader.load_extraction_operation')
    def test_main_returns_error_with_bad_credentials(self, extraction_mock, credential_mock):
        credential_mock.return_value = (None, ['Test error occured.'])
        extraction_mock.return_value = (Mock(), [])
        
        m = Mock(side_effect=select_file)
        with unittest.mock.patch('builtins.open', m):
            with unittest.mock.patch(
                'sys.argv',
                ['amaxa', '-c', 'credentials-bad.yaml', 'extraction-good.yaml']
            ):
                return_value = main()

        credential_mock.assert_called_once_with(yaml.safe_load(credentials_bad), False)

        extraction_mock.return_value[0].run.assert_not_called()

        self.assertEqual(-1, return_value)

    @unittest.mock.patch('amaxa.__main__.loader.load_credentials')
    @unittest.mock.patch('amaxa.__main__.loader.load_extraction_operation')
    def test_main_returns_error_with_bad_extraction(self, extraction_mock, credential_mock):
        context = Mock()
        credential_mock.return_value = (context, [])
        extraction_mock.return_value = (None, ['Test error occured.'])
        
        m = Mock(side_effect=select_file)
        with unittest.mock.patch('builtins.open', m):
            with unittest.mock.patch(
                'sys.argv',
                ['amaxa', '-c', 'credentials-good.yaml', 'extraction-bad.yaml']
            ):
                return_value = main()

        credential_mock.assert_called_once_with(yaml.safe_load(credentials_good_yaml), False)
        extraction_mock.assert_called_once_with(yaml.safe_load(extraction_bad), context)

        self.assertEqual(-1, return_value)
    
    @unittest.mock.patch('amaxa.__main__.loader.load_credentials')
    @unittest.mock.patch('amaxa.__main__.loader.load_extraction_operation')
    def test_main_returns_error_with_errors_during_extraction(self, extraction_mock, credential_mock):
        context = Mock()
        op = Mock()
        op.run = Mock(return_value=-1)
        op.stage = amaxa.LoadStage.INSERTS
        op.global_id_map = {}
        credential_mock.return_value = (context, [])
        extraction_mock.return_value = (op, [])
        
        m = Mock(side_effect=select_file)
        with unittest.mock.patch('builtins.open', m):
            with unittest.mock.patch(
                'sys.argv',
                ['amaxa', '-c', 'credentials-good.yaml', 'extraction-good.yaml']
            ):
                return_value = main()

        self.assertEqual(-1, return_value)

    @unittest.mock.patch('amaxa.__main__.loader.load_credentials')
    @unittest.mock.patch('amaxa.__main__.loader.load_extraction_operation')
    def test_main_saves_state_on_error(self, extraction_mock, credential_mock):
        context = Mock()
        op = Mock()
        op.run = Mock(return_value=-1)
        op.stage = amaxa.LoadStage.INSERTS
        op.global_id_map = { amaxa.SalesforceId('001000000000001'): amaxa.SalesforceId('001000000000002') }
        credential_mock.return_value = (context, [])
        extraction_mock.return_value = (op, [])
        
        m = Mock(side_effect=select_file)
        with unittest.mock.patch('builtins.open', m):
            with unittest.mock.patch(
                'sys.argv',
                ['amaxa', '-c', 'credentials-good.yaml', 'extraction-good.yaml']
            ):
                return_value = main()

        self.assertEqual(-1, return_value)
        self.assertLess(0, state_file.tell())

        state_file.seek(0)
        yaml_state = yaml.load(state_file)

        self.assertIn('state', yaml_state)
        self.assertIn('id-map', yaml_state['state'])
        self.assertIn('stage', yaml_state['state'])
        self.assertEqual(amaxa.LoadStage.INSERTS.value, yaml_state['state']['stage'])
        self.assertEqual(
            { str(k) : str(v) for k, v in op.global_id_map.items() },
            yaml_state['state']['id-map']
        )

    @unittest.mock.patch('amaxa.__main__.loader.load_credentials')
    @unittest.mock.patch('amaxa.__main__.loader.load_extraction_operation')
    def test_main_loads_state_with_use_state_option(self, extraction_mock, credential_mock):
        context = Mock()
        op = Mock()
        op.run = Mock(return_value=0)
        credential_mock.return_value = (context, [])
        extraction_mock.return_value = (op, [])
        
        m = Mock(side_effect=select_file)
        with unittest.mock.patch('builtins.open', m):
            with unittest.mock.patch(
                'sys.argv',
                ['amaxa', '-c', 'credentials-good.yaml', 'extraction-good.yaml', '--use-state', 'state-good.yaml']
            ):
                return_value = main()

        self.assertEqual(0, return_value)
        self.assertEqual(amaxa.LoadStage.INSERTS, op.stage)
        self.assertEqual(
            {
                amaxa.SalesforceId('001000000000001'): amaxa.SalesforceId('001000000000002'),
                amaxa.SalesforceId('001000000000003'): amaxa.SalesforceId('001000000000004')
            },
            op.global_id_map
        )
