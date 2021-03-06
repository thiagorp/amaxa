import unittest
import simple_salesforce
from unittest.mock import Mock
from .MockSimpleSalesforce import MockSimpleSalesforce
from .. import amaxa, loader


class test_load_extraction_operation(unittest.TestCase):
    def test_validate_extraction_schema_returns_normalized_input(self):
        (result, errors) = loader.validate_extraction_schema(
            {
                'version': 1,
                'operation': [
                    { 
                        'sobject': 'Account',
                        'fields': [ 'Name', 'ParentId' ],
                        'extract': { 'all': True }
                    }
                ]
            }
        )

        self.assertEqual('Account.csv', result['operation'][0]['file'])
        self.assertEqual([], errors)

    def test_validate_extraction_schema_returns_errors(self):
        (result, errors) = loader.validate_extraction_schema(
            {
                'operation': [
                    { 
                        'sobject': 'Account',
                        'fields': [ 'Name', 'ParentId' ],
                        'extract': { 'all': True }
                    }
                ]
            }
        )

        self.assertIsNone(result)
        self.assertEqual(['version: [\'required field\']'], errors)

    def test_load_extraction_operation_returns_validation_errors(self):
        context = Mock()
        (result, errors) = loader.load_extraction_operation(
            {
                'operation': [
                    { 
                        'sobject': 'Account',
                        'fields': [ 'Name', 'ParentId' ],
                        'extract': { 'all': True }
                    }
                ]
            },
            context
        )

        self.assertIsNone(result)
        self.assertEqual(['version: [\'required field\']'], errors)
        context.assert_not_called()

    def test_load_extraction_operation_returns_error_on_bad_ids(self):
        context = amaxa.ExtractOperation(MockSimpleSalesforce())

        (result, errors) = loader.load_extraction_operation(
            {
                'version': 1,
                'operation': [
                    { 
                        'sobject': 'Account',
                        'fields': [ 'Name' ],
                        'extract': { 
                            'ids': [
                                '001XXXXXXXXXXXXXXXXX',
                                ''
                            ] 
                        }
                    }
                ]
            },
            context
        )

        self.assertIsNone(result)
        self.assertEqual(['One or more invalid Id values provided for sObject Account'], errors)

    @unittest.mock.patch('simple_salesforce.Salesforce')
    def test_load_extraction_operation_traps_login_exceptions(self, sf_mock):
        return_exception = simple_salesforce.SalesforceAuthenticationFailed(500, 'Internal Server Error')
        sf_mock.describe = Mock(side_effect=return_exception)
        context = amaxa.ExtractOperation(sf_mock)
        ex = {
            'version': 1,
            'operation': [
                { 
                    'sobject': 'Account',
                    'field-group': 'readable',
                    'extract': { 'all': True }
                }
            ]
        }

        (result, errors) = loader.load_extraction_operation(ex, context)

        self.assertIsNone(result)
        self.assertEqual(['Unable to authenticate to Salesforce: {}'.format(return_exception)], errors)

    def test_load_extraction_operation_flags_missing_sobjects(self):
        context = amaxa.ExtractOperation(MockSimpleSalesforce())

        ex = { 
            'version': 1, 
            'operation': [
                { 
                    'sobject': 'Account',
                    'fields': [ 'Name' ],
                    'extract': { 'all': True }
                },
                {
                    'sobject': 'Test__c',
                    'fields': [ 'Name' ],
                    'extract': { 'all': True }
                }
            ]
        }
        m = unittest.mock.mock_open()
        with unittest.mock.patch('builtins.open', m):
            (result, errors) = loader.load_extraction_operation(ex, context)
        
        m.assert_not_called()

        self.assertIsNone(result)
        self.assertEqual(
            [ 'sObject Test__c does not exist or is not visible.' ],
            errors
        )
    
    def test_load_extraction_operation_flags_missing_fields(self):
        context = amaxa.ExtractOperation(MockSimpleSalesforce())

        ex = { 
            'version': 1, 
            'operation': [
                { 
                    'sobject': 'Account',
                    'fields': [ 'Name', 'Test__c' ],
                    'extract': { 'all': True }
                }
            ]
        }

        m = unittest.mock.mock_open()
        with unittest.mock.patch('builtins.open', m):
            (result, errors) = loader.load_extraction_operation(ex, context)

        m.assert_not_called()

        self.assertIsNone(result)
        self.assertEqual(
            [
                'Field Account.Test__c does not exist or is not visible.'
            ],
            errors
        )

    def test_load_extraction_operation_creates_valid_steps_with_files(self):
        context = amaxa.ExtractOperation(MockSimpleSalesforce())
        context.add_dependency = Mock()

        ex = {
            'version': 1,
            'operation': [
                { 
                    'sobject': 'Account',
                    'fields': [ 'Name' ],
                    'extract': { 'all': True }
                },
                { 
                    'sobject': 'Contact',
                    'fields': [ 'Name' ],
                    'extract': { 
                        'ids': [
                            '003000000000000',
                            '003000000000001'
                        ]
                    }
                },
                {
                    'sobject': 'Opportunity',
                    'fields': [ 'Name' ],
                    'extract': {
                        'descendents': True
                    }
                },
                {
                    'sobject': 'Task',
                    'fields': [ 'Id' ],
                    'extract': {
                        'query': 'AccountId != null'
                    }
                }

            ]
        }

        m = unittest.mock.mock_open()
        with unittest.mock.patch('builtins.open', m):
            (result, errors) = loader.load_extraction_operation(ex, context)

        self.assertEqual([], errors)
        self.assertIsInstance(result, amaxa.ExtractOperation)

        m.assert_has_calls(
            [
                unittest.mock.call('Account.csv', 'w'),
                unittest.mock.call('Contact.csv', 'w'),
                unittest.mock.call('Opportunity.csv', 'w'),
                unittest.mock.call('Task.csv', 'w')
            ],
            any_order=True
        )

        context.add_dependency.assert_has_calls(
            [
                unittest.mock.call('Contact', amaxa.SalesforceId('003000000000000')),
                unittest.mock.call('Contact', amaxa.SalesforceId('003000000000001'))
            ]
        )

        self.assertEqual(4, len(result.steps))
        self.assertEqual('Account', result.steps[0].sobjectname)
        self.assertEqual(amaxa.ExtractionScope.ALL_RECORDS, result.steps[0].scope)
        self.assertEqual('Contact', result.steps[1].sobjectname)
        self.assertEqual(amaxa.ExtractionScope.SELECTED_RECORDS, result.steps[1].scope)
        self.assertEqual('Opportunity', result.steps[2].sobjectname)
        self.assertEqual(amaxa.ExtractionScope.DESCENDENTS, result.steps[2].scope)
        self.assertEqual('Task', result.steps[3].sobjectname)
        self.assertEqual(amaxa.ExtractionScope.QUERY, result.steps[3].scope)

    @unittest.mock.patch('csv.DictWriter.writeheader')
    def test_load_extraction_operation_writes_correct_headers(self, dict_writer):
        context = amaxa.ExtractOperation(MockSimpleSalesforce())

        ex = {
            'version': 1,
            'operation': [
                { 
                    'sobject': 'Account',
                    'fields': [ 'Name', 'ParentId', 'Id' ],
                    'extract': { 'all': True }
                }
            ]
        }

        m = unittest.mock.mock_open()
        with unittest.mock.patch('builtins.open', m):
            (result, errors) = loader.load_extraction_operation(ex, context)
            

        self.assertEqual([], errors)
        self.assertIsInstance(result, amaxa.ExtractOperation)
        m.assert_called_once_with('Account.csv', 'w')
        csv_file = context.file_store.get_csv('Account', amaxa.FileType.OUTPUT)
        self.assertIsNotNone(csv_file)

        dict_writer.assert_called_once_with()
        self.assertEqual(
            ['Id', 'Name', 'ParentId'],
            csv_file.fieldnames
        )


    def test_load_extraction_operation_finds_readable_field_group(self):
        context = amaxa.ExtractOperation(MockSimpleSalesforce())

        ex = {
            'version': 1,
            'operation': [
                { 
                    'sobject': 'Account',
                    'field-group': 'readable',
                    'extract': { 'all': True }
                }
            ]
        }

        m = unittest.mock.mock_open()
        with unittest.mock.patch('builtins.open', m):
            (result, errors) = loader.load_extraction_operation(ex, context)

        self.assertEqual([], errors)
        self.assertIsInstance(result, amaxa.ExtractOperation)
        m.assert_called_once_with('Account.csv', 'w')

        self.assertEqual(
            set(context.get_filtered_field_map('Account', lambda x: x['type'] != 'address')), 
            result.steps[0].field_scope
        )

    def test_load_extraction_operation_finds_writeable_field_group(self):
        context = amaxa.ExtractOperation(MockSimpleSalesforce())

        ex = {
            'version': 1,
            'operation': [
                { 
                    'sobject': 'Account',
                    'field-group': 'writeable',
                    'extract': { 'all': True }
                }
            ]
        }

        m = unittest.mock.mock_open()
        with unittest.mock.patch('builtins.open', m):
            (result, errors) = loader.load_extraction_operation(ex, context)

        self.assertEqual([], errors)
        self.assertIsInstance(result, amaxa.ExtractOperation)
        m.assert_called_once_with('Account.csv', 'w')

        self.assertEqual(1, len(result.steps))
        self.assertEqual(
            set(context.get_filtered_field_map('Account', lambda x: x['createable'])) | set(['Id']),
            result.steps[0].field_scope
        )

    def test_load_extraction_operation_readable_field_group_omits_unsupported_types(self):
        context = amaxa.ExtractOperation(MockSimpleSalesforce())

        ex = {
            'version': 1,
            'operation': [
                { 
                    'sobject': 'Account',
                    'field-group': 'readable',
                    'extract': { 'all': True }
                }
            ]
        }

        m = unittest.mock.mock_open()
        with unittest.mock.patch('builtins.open', m):
            (result, errors) = loader.load_extraction_operation(ex, context)

        self.assertEqual([], errors)
        self.assertIsInstance(result, amaxa.ExtractOperation)
        m.assert_called_once_with('Account.csv', 'w')

        self.assertEqual(1, len(result.steps))
        self.assertNotIn('BillingAddress', result.steps[0].field_scope)

    def test_load_extraction_operation_writeable_field_group_omits_unsupported_types(self):
        context = amaxa.ExtractOperation(MockSimpleSalesforce())

        ex = {
            'version': 1,
            'operation': [
                { 
                    'sobject': 'Attachment',
                    'field-group': 'writeable',
                    'extract': { 'all': True }
                }
            ]
        }

        m = unittest.mock.mock_open()
        with unittest.mock.patch('builtins.open', m):
            (result, errors) = loader.load_extraction_operation(ex, context)

        self.assertEqual([], errors)
        self.assertIsInstance(result, amaxa.ExtractOperation)
        m.assert_called_once_with('Attachment.csv', 'w')

        self.assertEqual(1, len(result.steps))
        self.assertNotIn('Body', result.steps[0].field_scope)

    def test_load_extraction_operation_generates_field_list(self):
        context = amaxa.ExtractOperation(MockSimpleSalesforce())

        ex = {
            'version': 1,
            'operation': [
                { 
                    'sobject': 'Account',
                    'fields': [
                        'Name', 
                        'Industry'
                    ],
                    'extract': { 'all': True }
                }
            ]
        }

        m = unittest.mock.mock_open()
        with unittest.mock.patch('builtins.open', m):
            (result, errors) = loader.load_extraction_operation(ex, context)

        self.assertEqual([], errors)
        self.assertIsInstance(result, amaxa.ExtractOperation)
        m.assert_called_once_with('Account.csv', 'w')

        self.assertEqual({'Name', 'Industry', 'Id'}, result.steps[0].field_scope)

    def test_load_extraction_operation_creates_export_mapper(self):
        context = amaxa.ExtractOperation(MockSimpleSalesforce())

        ex = {
            'version': 1,
            'operation': [
                { 
                    'sobject': 'Account',
                    'fields': [
                        {
                            'field': 'Name',
                            'column': 'Account Name',
                            'transforms': ['strip', 'lowercase']
                        },
                        'Industry'
                    ],
                    'extract': { 'all': True }
                }
            ]
        }

        m = unittest.mock.mock_open()
        with unittest.mock.patch('builtins.open', m):
            (result, errors) = loader.load_extraction_operation(ex, context)

        self.assertEqual([], errors)
        self.assertIsInstance(result, amaxa.ExtractOperation)
        m.assert_called_once_with('Account.csv', 'w')

        self.assertEqual({'Name', 'Industry', 'Id'}, result.steps[0].field_scope)
        self.assertIn('Account', context.mappers)

        mapper = context.mappers['Account']
        self.assertEqual(
            {'Account Name': 'university of caprica', 'Industry': 'Education'},
            mapper.transform_record({ 'Name': 'UNIversity of caprica  ', 'Industry': 'Education' })
        )

    def test_load_extraction_operation_returns_error_base64_fields(self):
        context = amaxa.ExtractOperation(MockSimpleSalesforce())

        ex = {
            'version': 1,
            'operation': [
                { 
                    'sobject': 'Attachment',
                    'fields': [
                        'Name', 
                        'Body'
                    ],
                    'extract': { 'all': True }
                }
            ]
        }

        m = unittest.mock.mock_open()
        with unittest.mock.patch('builtins.open', m):
            (result, errors) = loader.load_extraction_operation(ex, context)

        self.assertEqual(['Field {}.{} is a base64 field, which is not supported.'.format('Attachment', 'Body')], errors)
        self.assertIsNone(result)
        m.assert_not_called()

    def test_load_extraction_operation_catches_duplicate_columns(self):
        context = amaxa.ExtractOperation(MockSimpleSalesforce())

        ex = {
            'version': 1,
            'operation': [
                { 
                    'sobject': 'Account',
                    'fields': [
                        {
                            'field': 'Name',
                            'column': 'Industry',
                        },
                        'Industry',
                        {
                            'field': 'Description',
                            'column': 'Industry'
                        }
                    ],
                    'extract': { 'all': True }
                }
            ]
        }

        m = unittest.mock.mock_open()
        with unittest.mock.patch('builtins.open', m):
            (result, errors) = loader.load_extraction_operation(ex, context)

        self.assertIsNone(result)
        self.assertEqual(
            ['Field Account.Industry is mapped to column Industry, but this column is already mapped.',
            'Field Account.Description is mapped to column Industry, but this column is already mapped.'],
            errors
        )

    def test_load_extraction_operation_catches_duplicate_fields(self):
        context = amaxa.ExtractOperation(MockSimpleSalesforce())

        ex = {
            'version': 1,
            'operation': [
                { 
                    'sobject': 'Account',
                    'fields': [
                        {
                            'field': 'Name',
                            'column': 'Industry',
                        },
                        {
                            'field': 'Name',
                            'column': 'Name'
                        }
                    ],
                    'extract': { 'all': True }
                }
            ]
        }

        m = unittest.mock.mock_open()
        with unittest.mock.patch('builtins.open', m):
            (result, errors) = loader.load_extraction_operation(ex, context)

        self.assertIsNone(result)
        self.assertEqual(
            ['Field Account.Name is present more than once in the specification.'],
            errors
        )

    def test_load_extraction_operation_populates_lookup_behaviors(self):
        context = amaxa.ExtractOperation(MockSimpleSalesforce())

        ex = {
            'version': 1,
            'operation': [
                { 
                    'sobject': 'Account',
                    'fields': [
                        'Name',
                        {
                            'field': 'ParentId',
                            'self-lookup-behavior': 'trace-none'
                        }
                    ],
                    'extract': { 'all': True }
                },
                {
                    'sobject': 'Task',
                    'fields': [
                        {
                            'field': 'WhatId',
                            'outside-lookup-behavior': 'drop-field'
                        }
                    ],
                    'extract': { 'all': True }
                }
            ]
        }

        m = unittest.mock.mock_open()
        with unittest.mock.patch('builtins.open', m):
            (result, errors) = loader.load_extraction_operation(ex, context)

        self.assertEqual([], errors)
        self.assertIsInstance(result, amaxa.ExtractOperation)

        self.assertEqual(amaxa.SelfLookupBehavior.TRACE_NONE, result.steps[0].get_self_lookup_behavior_for_field('ParentId'))
        self.assertEqual(amaxa.OutsideLookupBehavior.DROP_FIELD, result.steps[1].get_outside_lookup_behavior_for_field('WhatId'))

    def test_load_extraction_operation_validates_lookup_behaviors_for_self_lookups(self):
        context = amaxa.ExtractOperation(MockSimpleSalesforce())

        ex = {
            'version': 1,
            'operation': [
                { 
                    'sobject': 'Account',
                    'fields': [
                        'Name',
                        {
                            'field': 'ParentId',
                            'outside-lookup-behavior': 'include'
                        }
                    ],
                    'extract': { 'all': True }
                }
            ]
        }

        m = unittest.mock.mock_open()
        with unittest.mock.patch('builtins.open', m):
            (result, errors) = loader.load_extraction_operation(ex, context)

        self.assertEqual(
            [
                'Lookup behavior \'{}\' specified for field {}.{} is not valid for this lookup type.'.format(
                    'include',
                    'Account',
                    'ParentId'
                )
            ],
            errors
        )
        self.assertIsNone(result)

    def test_load_extraction_operation_validates_lookup_behaviors_for_dependent_lookups(self):
        context = amaxa.ExtractOperation(MockSimpleSalesforce())

        ex = {
            'version': 1,
            'operation': [
                { 
                    'sobject': 'Contact',
                    'fields': [ 
                        {
                            'field': 'AccountId',
                            'self-lookup-behavior': 'trace-all'
                        }
                    ],
                    'extract': { 'all': True }
                },
                { 
                    'sobject': 'Account',
                    'fields': [
                        'Name'
                    ],
                    'extract': { 'all': True }
                }
            ]
        }

        m = unittest.mock.mock_open()
        with unittest.mock.patch('builtins.open', m):
            (result, errors) = loader.load_extraction_operation(ex, context)

        self.assertEqual(
            [
                'Lookup behavior \'{}\' specified for field {}.{} is not valid for this lookup type.'.format(
                    'trace-all',
                    'Contact',
                    'AccountId'
                )
            ],
            errors
        )
        self.assertIsNone(result)

    @unittest.mock.patch('logging.getLogger')
    def test_load_extraction_operation_warns_lookups_other_objects(self, logger):
        context = amaxa.ExtractOperation(MockSimpleSalesforce())
        amaxa_logger = Mock()
        logger.return_value=amaxa_logger

        ex = {
            'version': 1,
            'operation': [
                { 
                    'sobject': 'Contact',
                    'fields': [ 'AccountId' ],
                    'extract': { 'all': True }
                }
            ]
        }

        m = unittest.mock.mock_open()
        with unittest.mock.patch('builtins.open', m):
            (result, errors) = loader.load_extraction_operation(ex, context)

        self.assertEqual([], errors)
        self.assertIsInstance(result, amaxa.ExtractOperation)
        amaxa_logger.warning.assert_called_once_with(
            'Field %s.%s is a reference none of whose targets (%s) are included in the extraction. Reference handlers will be inactive for references to non-included sObjects.',
            'Contact',
            'AccountId',
            ', '.join(['Account'])
        )
