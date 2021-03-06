import simple_salesforce
import unittest
from unittest.mock import patch, Mock
from .. import amaxa, loader


class test_load_credentials(unittest.TestCase):
    def test_credential_schema_validates_username_password(self):
        (result, errors) = loader.validate_credential_schema(
            {
                'version': 1,
                'credentials': {
                    'password': '123456',
                    'username': 'baltar@ucaprica.cc',
                    'security-token': '98765',
                    'sandbox': True
                }
            }
        )

        self.assertIsNotNone(result)
        self.assertEqual([], errors)

    def test_credential_schema_validates_access_token(self):
        (result, errors) = loader.validate_credential_schema(
            {
                'version': 1,
                'credentials': {
                    'access-token': 'ABCDEF123456',
                    'instance-url': 'test.salesforce.com'
                }
            }
        )

        self.assertIsNotNone(result)
        self.assertEqual([], errors)

    def test_credential_schema_validates_jwt(self):
        (result, errors) = loader.validate_credential_schema(
            {
                'version': 1,
                'credentials': {
                    'consumer-key': 'ABCDEF123456',
                    'jwt-key': '--BEGIN KEY HERE--',
                    'username': 'baltar@ucaprica.cc'
                }
            }
        )

        self.assertIsNotNone(result)
        self.assertEqual([], errors)

    def test_credential_schema_validates_jwt_key_file(self):
        (result, errors) = loader.validate_credential_schema(
            {
                'version': 1,
                'credentials': {
                    'consumer-key': 'ABCDEF123456',
                    'jwt-file': 'jwt.key',
                    'username': 'baltar@ucaprica.cc'
                }
            }
        )

        self.assertIsNotNone(result)
        self.assertEqual([], errors)

    def test_credential_schema_fails_mixed_values(self):
        (result, errors) = loader.validate_credential_schema(
            {
                'version': 1, 
                'credentials': {
                    'password': '123456',
                    'username': 'baltar@ucaprica.cc',
                    'security-token': '98765',
                    'sandbox': True,
                    'instance-url': 'test.salesforce.com'
                }
            }
        )

        self.assertIsNone(result)
        self.assertGreater(len(errors), 0)

    def test_validate_credential_schema_returns_normalized_input(self):
        credentials = {
            'version': 1,
            'credentials': {
                'username': 'baltar@ucaprica.edu',
                'password': '666666666'
            }
        }

        (result, errors) = loader.validate_credential_schema(credentials)

        self.assertEqual(False, result['credentials']['sandbox'])
        self.assertEqual([], errors)

    def test_validate_credential_schema_returns_errors(self):
        credentials = {
            'credentials': {
                'username': 'baltar@ucaprica.edu',
                'password': '666666666'
            }
        }

        (result, errors) = loader.validate_credential_schema(credentials)

        self.assertIsNone(result)
        self.assertEqual(['version: [\'required field\']'], errors)

    @patch('simple_salesforce.Salesforce')
    def test_load_credentials_uses_username_password(self, sf_mock):
        (result, errors) = loader.load_credentials(
            {
                'version': 1,
                'credentials': {
                    'password': '123456',
                    'username': 'baltar@ucaprica.cc',
                    'security-token': '98765',
                    'sandbox': True
                }
            },
            False
        )

        self.assertEqual([], errors)
        self.assertIsNotNone(result)
        
        sf_mock.assert_called_once_with(
            username='baltar@ucaprica.cc',
            password='123456',
            security_token='98765',
            organizationId='',
            sandbox=True
        )

    @patch('requests.post')
    @patch('jwt.encode')
    @patch('simple_salesforce.Salesforce')
    def test_load_credentials_uses_jwt_key(self, sf_mock, jwt_mock, requests_mock):
        requests_mock.return_value.status_code = 200
        requests_mock.return_value.json = Mock(
            return_value = {
                'instance_url': 'test.salesforce.com',
                'access_token': 'swordfish'
            }
        )
        (result, errors) = loader.load_credentials(
            {
                'version': 1,
                'credentials': {
                    'consumer-key': '123456',
                    'username': 'baltar@ucaprica.cc',
                    'jwt-key': '00000',
                    'sandbox': True
                }
            },
            False
        )

        self.assertEqual([], errors)
        self.assertIsNotNone(result)

        jwt_mock.assert_called()
        requests_mock.assert_called_once_with(
            'https://test.salesforce.com/services/oauth2/token',
            data={
                'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                'assertion': jwt_mock.return_value
            }
        )
        
        sf_mock.assert_called_once_with(
            session_id = 'swordfish',
            instance_url = 'test.salesforce.com'
        )

    @patch('requests.post')
    @patch('jwt.encode')
    @patch('simple_salesforce.Salesforce')
    def test_load_credentials_uses_jwt_file(self, sf_mock, jwt_mock, requests_mock):
        requests_mock.return_value.status_code = 200
        requests_mock.return_value.json = Mock(
            return_value = {
                'instance_url': 'test.salesforce.com',
                'access_token': 'swordfish'
            }
        )

        m = unittest.mock.mock_open(read_data='00000')
        with patch('builtins.open', m):
            (result, errors) = loader.load_credentials(
                {
                    'version': 1,
                    'credentials': {
                        'consumer-key': '123456',
                        'username': 'baltar@ucaprica.cc',
                        'jwt-file': 'jwt.key',
                        'sandbox': True
                    }
                },
                False
            )

        self.assertEqual([], errors)
        self.assertIsNotNone(result)

        m.assert_any_call('jwt.key', 'r')
        jwt_mock.assert_called()
        requests_mock.assert_called_once_with(
            'https://test.salesforce.com/services/oauth2/token',
            data={
                'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                'assertion': jwt_mock.return_value
            }
        )
        
        sf_mock.assert_called_once_with(
            session_id = 'swordfish',
            instance_url = 'test.salesforce.com'
        )

    @patch('requests.post')
    @patch('jwt.encode')
    @patch('simple_salesforce.Salesforce')
    def test_load_credentials_returns_error_on_jwt_key_failure(self, sf_mock, jwt_mock, requests_mock):
        body = { 'error': 'bad JWT', 'error_description': 'key error' }
        requests_mock.return_value.status_code = 400
        requests_mock.return_value.json = Mock(
            return_value = body
        )
        (result, errors) = loader.load_credentials(
            {
                'version': 1,
                'credentials': {
                    'consumer-key': '123456',
                    'username': 'baltar@ucaprica.cc',
                    'jwt-key': '00000',
                    'sandbox': True
                }
            },
            False
        )

        self.assertIsNone(result)
        self.assertEqual(
            [
                'Failed to authenticate with JWT: {}'.format(
                    simple_salesforce.exceptions.SalesforceAuthenticationFailed(
                        body['error'],
                        body['error_description']
                    ).message
                )
            ],
            errors
        )

    @patch('requests.post')
    @patch('jwt.encode')
    @patch('simple_salesforce.Salesforce')
    def test_load_credentials_returns_error_on_jwt_file_failure(self, sf_mock, jwt_mock, requests_mock):
        body = { 'error': 'bad JWT', 'error_description': 'key error' }
        requests_mock.return_value.status_code = 400
        requests_mock.return_value.json = Mock(
            return_value = body
        )
        m = unittest.mock.mock_open(read_data='00000')
        with patch('builtins.open', m):
            (result, errors) = loader.load_credentials(
                {
                    'version': 1,
                    'credentials': {
                        'consumer-key': '123456',
                        'username': 'baltar@ucaprica.cc',
                        'jwt-file': 'server.key',
                        'sandbox': True
                    }
                },
                False
            )

        self.assertIsNone(result)
        self.assertEqual(
            [
                'Failed to authenticate with JWT: {}'.format(
                    simple_salesforce.exceptions.SalesforceAuthenticationFailed(
                        body['error'],
                        body['error_description']
                    ).message
                )
            ],
            errors
        )

    @patch('simple_salesforce.Salesforce')
    def test_load_credentials_uses_access_token(self, sf_mock):
        (result, errors) = loader.load_credentials(
            {
                'version': 1,
                'credentials': {
                    'access-token': 'ABCDEF123456',
                    'instance-url': 'test.salesforce.com'
                }
            },
            False
        )

        self.assertEqual([], errors)
        self.assertIsNotNone(result)
        
        sf_mock.assert_called_once_with(
            session_id='ABCDEF123456',
            instance_url='test.salesforce.com'
        )

    @patch('simple_salesforce.Salesforce')
    def test_load_credentials_returns_validation_errors(self, sf_mock):
        credentials = {
            'credentials': {
                'username': 'baltar@ucaprica.edu',
                'password': '666666666'
            }
        }

        (result, errors) = loader.load_credentials(credentials, False)

        self.assertIsNone(result)
        self.assertEqual(['version: [\'required field\']'], errors)

    @patch('simple_salesforce.Salesforce')
    def test_load_credentials_returns_error_without_credentials(self, sf_mock):
        credentials = {
            'version': 1,
            'credentials': {
            }
        }

        (result, errors) = loader.load_credentials(credentials, False)

        self.assertIsNone(result)
        self.assertEqual(['A set of valid credentials was not provided.'], errors)
