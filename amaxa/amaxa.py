import functools
import simple_salesforce
import logging
from . import constants
from enum import Enum, unique

@unique
class StringEnum(Enum):
    @classmethod
    def all_values(cls):
        return [m.value for m in cls]
    
    @classmethod
    def values_dict(cls):
        return { m.value : m for m in cls }

class ExtractionScope(StringEnum):
    ALL_RECORDS = 'all'
    QUERY = 'query'
    SELECTED_RECORDS = 'some'
    DESCENDENTS = 'children'

class SelfLookupBehavior(StringEnum):
    TRACE_ALL = 'trace-all'
    TRACE_NONE = 'trace-none'

class OutsideLookupBehavior(StringEnum):
    DROP_FIELD = 'drop-field'
    INCLUDE = 'include'
    ERROR = 'error'

class AmaxaException(Exception):
    pass

class SalesforceId(object):
    def __init__(self, idstr):
        if isinstance(idstr, SalesforceId):
            self.id = idstr.id
        else:
            idstr = idstr.strip()
            if len(idstr) == 15:
                suffix = ''
                for i in range(0, 3):
                    baseTwo = 0
                    for j in range (0, 5):
                        character = idstr[i*5+j]
                        if character >= 'A' and character <= 'Z':
                            baseTwo += 1 << j
                    suffix += 'ABCDEFGHIJKLMNOPQRSTUVWXYZ012345'[baseTwo]
                self.id = idstr + suffix
            elif len(idstr) == 18:
                self.id = idstr
            else:
                raise ValueError('Salesforce Ids must be 15 or 18 characters.')

    def __eq__(self, other):
        if isinstance(other, SalesforceId):
            return self.id == other.id
        elif isinstance(other, str):
            return self.id == SalesforceId(other).id

        return False

    def __hash__(self):
        return hash(self.id)

    def __str__(self):
        return self.id

    def __repr__(self):
        return self.id

class Operation(object):
    def __init__(self, connection):
        self.steps = []
        self.connection = connection
        self.describe_info = {}
        self.field_maps = {}
        self.proxy_objects = {}
        self.bulk_proxy_objects = {}
        self.key_prefix_map = None
        self.logger = logging.getLogger('amaxa')

    def execute(self):
        pass

    def add_step(self, step):
        step.context = self
        self.steps.append(step)

    def get_sobject_list(self):
        return [step.sobjectname for step in self.steps]

    def get_sobject_name_for_id(self, id):
        if self.key_prefix_map is None:
            global_describe = self.connection.describe()['sobjects']
            self.key_prefix_map = {
                global_describe[name]['keyPrefix']: name for name in global_describe
            }
        
        return self.key_prefix_map[id[:3]]

    def get_proxy_object(self, sobjectname):
        if sobjectname not in self.proxy_objects:
            self.proxy_objects[sobjectname] = getattr(self.connection, sobjectname)

        return self.proxy_objects[sobjectname]

    def get_bulk_proxy_object(self, sobjectname):
        if sobjectname not in self.bulk_proxy_objects:
            self.bulk_proxy_objects[sobjectname] = getattr(self.connection.bulk, sobjectname)

        return self.bulk_proxy_objects[sobjectname]

    def get_describe(self, sobjectname):
        if sobjectname not in self.describe_info:
            self.describe_info[sobjectname] = self.get_proxy_object(sobjectname).describe()
            self.field_maps[sobjectname] = { f.get('name') : f for f in self.describe_info[sobjectname].get('fields') }

        return self.describe_info[sobjectname]

    def get_field_map(self, sobjectname):
        if sobjectname not in self.describe_info:
            self.get_describe(sobjectname)

        return self.field_maps[sobjectname]

    def get_filtered_field_map(self, sobjectname, lam):
        field_map = self.get_field_map(sobjectname)

        return { k: field_map[k] for k in field_map if lam(field_map[k]) }


class Step(object):
    def __init__(self, sobjectname, field_scope):
        self.sobjectname = sobjectname
        self.field_scope = field_scope
        self.context = None

    def get_field_list(self):
        return ', '.join(self.field_scope)

    def scan_fields(self):
        # Determine whether we have any self-lookups or dependent lookups
        field_map = self.context.get_field_map(self.sobjectname)
        sobjects = self.context.get_sobject_list()

        # Filter for lookup fields that have at least one referent that is part of
        # this extraction. Users will see a warning for other lookups (on load),
        # and we'll just treat them like normal exported non-lookup fields
        self.all_lookups = { 
            f for f in self.field_scope 
              if field_map[f]['type'] == 'reference'
                 and any([s in sobjects for s in field_map[f]['referenceTo']])
        }

        # Filter for lookup fields that are self-lookups
        # At present, we are assuming that there are no polymorphic self-lookup fields
        # in Salesforce. Should these exist, we'd have potential issues.
        self.self_lookups = { 
            f for f in self.all_lookups if self.sobjectname in field_map[f]['referenceTo']
        }

        # Filter for descendent lookups - fields that lookup to an object above this one
        # in the extraction and can be used to identify descendent records of *this* object
        self.descendent_lookups = {
            f for f in self.all_lookups
            if any([sobjects.index(refTo) < sobjects.index(self.sobjectname) 
                    for refTo in field_map[f]['referenceTo'] if refTo in sobjects])
        }

        # Filter for dependent lookups - fields that look up to an object
        # below this one in the extraction. These fields automatically have
        # dependencies registered when they're extracted.

        # A (polymorphic) field may be both a descendent lookup (up the hierarchy)
        # and a dependent lookup (down the hierarchy), as well as a lookup
        # to some arbitrary object outside the hierarchy.
        self.dependent_lookups = { 
            f for f in self.all_lookups
            if any([sobjects.index(refTo) > sobjects.index(self.sobjectname) 
                    for refTo in field_map[f]['referenceTo'] if refTo in sobjects])
        }

    def execute(self):
        pass


class LoadOperation(Operation):
    def __init__(self, connection):
        super().__init__(connection)
        self.input_files = {}
        self.result_files = {}
        self.mappers = {}
        self.global_id_map = {}

    def set_input_file(self, sobjectname, f):
        self.input_files[sobjectname] = f

    def get_input_file(self, sobjectname):
        return self.input_files[sobjectname]

    def set_result_file(self, sobjectname, f):
        self.result_files[sobjectname] = f
    
    def get_result_file(self, sobjectname):
        return self.result_files[sobjectname]

    def register_new_id(self, sobjectname, old_id, new_id):
        self.global_id_map[old_id] = new_id
        if sobjectname in self.result_files:
            self.result_files[sobjectname].writerow(
                {
                    constants.ORIGINAL_ID: str(old_id),
                    constants.NEW_ID: str(new_id)
                }
            )

    def get_new_id(self, old_id):
        return self.global_id_map.get(old_id, None)

    def execute(self):
        self.logger.info('Starting load with sObjects %s', self.get_sobject_list())
        for s in self.steps:
            s.scan_fields()
            self.logger.info('Loading %s', s.sobjectname)
            s.execute()

            # After each step, check whether errors happened and stop the process.
            if len(s.errors) > 0:
                self.logger.error('Errors took place during load of %s:\n%s', s.sobjectname, '\n'.join(s.errors))
                return -1
        
        for s in self.steps:
            self.logger.info('Populating dependent and self-lookups for %s', s.sobjectname)
            s.execute_dependent_updates()

            if len(s.errors) > 0:
                self.logger.error('Errors took place during dependent updates for %s:\n%s', s.sobjectname, '\n'.join(s.errors))
                return -1

        return 0

class LoadStep(Step):
    def __init__(self, sobjectname, field_scope, outside_lookup_behavior=OutsideLookupBehavior.INCLUDE):
        self.sobjectname = sobjectname
        self.field_scope = field_scope
        self.outside_lookup_behavior = outside_lookup_behavior
        self.lookup_behaviors = {}
        self.errors = []
        self.dependent_lookup_records = []

        self.context = None

    def set_lookup_behavior_for_field(self, field, behavior):
        self.lookup_behaviors[field] = behavior

    def get_lookup_behavior_for_field(self, field):
        return self.lookup_behaviors.get(field, self.outside_lookup_behavior)

    def get_value_for_lookup(self, lookup, value, record_id):
        if value == '':
            return ''

        b = self.get_lookup_behavior_for_field(lookup)

        mapped_id = self.context.get_new_id(SalesforceId(value))

        if mapped_id is not None:
            return str(mapped_id)
        elif b is OutsideLookupBehavior.INCLUDE:
            return value
        elif b is OutsideLookupBehavior.ERROR:
            raise AmaxaException(
                '{} {} has an outside reference in field {} ({}), which is not allowed by the extraction configuration.',
                self.sobjectname, record_id, lookup, value
            )
        elif b is OutsideLookupBehavior.DROP_FIELD:
            return ''

    def populate_lookups(self, record, lookups, id):
        return { k: record[k] if k not in lookups
                              else self.get_value_for_lookup(k, record[k], id)
                 for k in record }

    def primitivize(self, record):
        # We're using the Bulk API over JSON, so values can be specified as strings (not converted to JSON primitives)
        # We will apply a light transformation to ensure we format correctly and respect a few Boolean equivalents
        def convert_value(value, field_type):
            if field_type == 'xsd:boolean':
                if value is None or value.lower() in ['no', 'false', 'n', 'f', '0', '']:
                    return 'false'
                elif value.lower() in ['yes', 'true', 'y', 't', '1']:
                    return 'true'
                raise ValueError('Invalid Boolean value {}', value)
            elif value is None or len(value) == 0:
                return None
            elif field_type == 'tns:ID':
                return str(value)
            elif field_type in ['xsd:string', 'xsd:date', 'xsd:dateTime', 'xsd:int', 'xsd:double']:
                return value
            
            return None

        field_map = self.context.get_field_map(self.sobjectname)
        return { k: convert_value(record[k], field_map[k]['soapType'] ) for k in record }

    def transform_record(self, record):
        if self.sobjectname in self.context.mappers:
            record = self.context.mappers[self.sobjectname].transform_record(record)

        return { k: record[k] for k in record if k in self.field_scope }

    def clean_dependent_lookups(self, record):
        all_lookups = self.dependent_lookups | self.self_lookups

        return { k: record[k] for k in record if k not in all_lookups }
    
    def extract_dependent_lookups(self, record):
        all_lookups = self.dependent_lookups | self.self_lookups

        return { k: record[k] for k in record if k in all_lookups or k == 'Id' }

    def execute(self):
        # Read our incoming file.
        # Apply transformations specified in our configuration file (column name -> field name, for example)
        # Then, populate all direct lookups. Dependent lookups and self-lookups will be populated in a later pass.
        records_to_load = []
        original_ids = []

        reader = self.context.get_input_file(self.sobjectname)
        for record in reader:
            # We need to save off the original record Id because it'll be cleaned from the record before insert.
            # We use the original Id for error reporting.
            original_ids.append(record['Id'])
            # We also need (before we clean the record) to save off a copy for population of its dependent lookups in a later pass.
            # Confirm first that we have a nonzero count of populated dependent lookups (we'll recheck in execute_dependent_updates)
            dependent_record = self.extract_dependent_lookups(record)
            if len([r for r in dependent_record.values() if r is not None and r != '']) > 1: # 1 for the Id
                self.dependent_lookup_records.append(dependent_record)

            # Finally, prep this record for the Bulk API, populate its lookups, apply transforms, and clean dependent lookups
            try:
                record = self.primitivize(
                    self.populate_lookups(
                        self.clean_dependent_lookups(
                            self.transform_record(
                                record
                            )
                        ),
                        self.descendent_lookups,
                        original_ids[-1]
                    )
                )
                records_to_load.append(record)
            except AmaxaException as e:
                self.errors.append(str(e))
            except ValueError as e:
                self.errors.append('Bad data in record {}: {}'.format(original_ids[-1], str(e)))

        if len(self.errors) > 0:
            return

        results = self.context.get_bulk_proxy_object(self.sobjectname).insert(records_to_load)
        for i, r in enumerate(results):
            if r['success']:
                self.context.register_new_id(
                    self.sobjectname,
                    SalesforceId(original_ids[i]),
                    SalesforceId(r['id']) # note lowercase in result
                )
            else:
                self.errors.append('Failed to load {} {}'.format(self.sobjectname, original_ids[i]))
    
    def execute_dependent_updates(self):
        # Populate dependent and self-lookups in a single pass
        records_to_load = []
        original_ids = []
        all_lookups = self.dependent_lookups | self.self_lookups

        if len(all_lookups) > 0:
            # Re-check, for each record, whether we have any loading to do.
            # If all of the dependent lookups prove to be dropped outside references, we have no work to do.
            for record in self.dependent_lookup_records:
                try:
                    cleaned_record = self.populate_lookups(record, all_lookups, record['Id'])
                    if len([r for r in cleaned_record.values() if r is not None and r != '']) > 1: # 1 for the Id
                        # Populate the new Id for this record
                        original_ids.append(cleaned_record['Id'])
                        cleaned_record['Id'] = str(self.context.get_new_id(SalesforceId(cleaned_record['Id'])))
                        records_to_load.append(cleaned_record)
                except AmaxaException as e:
                    self.errors.append(str(e))
            
            if len(records_to_load) > 0 and len(self.errors) == 0:
                results = self.context.get_bulk_proxy_object(self.sobjectname).update(records_to_load)
                for i, r in enumerate(results):
                    if not r['success']:
                        self.errors.append('Failed to execute dependent updates for {} {}'.format(self.sobjectname, original_ids[i]))


class ExtractOperation(Operation):
    def __init__(self, connection):
        super().__init__(connection)
        self.required_ids = {}
        self.extracted_ids = {}
        self.output_files = {}
        self.mappers = {}

    def execute(self):
        self.logger.info('Starting extraction with sObjects %s', self.get_sobject_list())
        for s in self.steps:
            self.logger.info('Extracting %s', s.sobjectname)
            s.execute()
            if len(s.errors) > 0:
                self.logger.error('Errors took place during extraction of %s:\n%s', s.sobjectname, '\n'.join(s.errors))
                return -1
            else:
                self.logger.info('Extracted %d records from %s', len(self.get_extracted_ids(s.sobjectname)), s.sobjectname)

        return 0

    def set_output_file(self, sobjectname, f):
        self.output_files[sobjectname] = f

    def add_dependency(self, sobjectname, id):
        if sobjectname not in self.required_ids:
            self.required_ids[sobjectname] = set()
        if id not in self.get_extracted_ids(sobjectname):
            self.required_ids[sobjectname].add(id)

    def get_dependencies(self, sobjectname):
        return self.required_ids[sobjectname] if sobjectname in self.required_ids else set()

    def get_sobject_ids_for_reference(self, sobjectname, field):
        ids = set()
        for name in self.get_field_map(sobjectname)[field]['referenceTo']:
            # For each sObject that we've extracted data for,
            # if that object is a potential reference target for this field,
            # accumulate those Ids in a Set.
            if name in self.extracted_ids:
                ids |= self.extracted_ids[name]

        return ids

    def get_extracted_ids(self, sobjectname):
        return self.extracted_ids[sobjectname] if sobjectname in self.extracted_ids else set()

    def store_result(self, sobjectname, record):
        if sobjectname not in self.extracted_ids:
            self.extracted_ids[sobjectname] = set()

        self.logger.debug('%s: extracting record %s', sobjectname, SalesforceId(record['Id']))
        if SalesforceId(record['Id']) not in self.extracted_ids[sobjectname]:
            self.extracted_ids[sobjectname].add(SalesforceId(record['Id']))
            self.output_files[sobjectname].writerow(
                self.mappers[sobjectname].transform_record(record) if sobjectname in self.mappers
                else record
            )

        if sobjectname in self.required_ids and SalesforceId(record['Id']) in self.required_ids[sobjectname]:
            self.required_ids[sobjectname].remove(SalesforceId(record['Id']))


class ExtractionStep(Step):
    def __init__(self, sobjectname, scope, field_scope, where_clause=None, self_lookup_behavior=SelfLookupBehavior.TRACE_ALL, outside_lookup_behavior=OutsideLookupBehavior.INCLUDE):
        super().__init__(sobjectname, field_scope)
        self.scope = scope
        self.where_clause = where_clause
        self.self_lookup_behavior = self_lookup_behavior
        self.outside_lookup_behavior = outside_lookup_behavior
        self.lookup_behaviors = {}
        self.errors = []

    def set_lookup_behavior_for_field(self, f, behavior):
        self.lookup_behaviors[f] = behavior

    def get_self_lookup_behavior_for_field(self, f):
        return self.lookup_behaviors.get(f, self.self_lookup_behavior)
    
    def get_outside_lookup_behavior_for_field(self, f):
        return self.lookup_behaviors.get(f, self.outside_lookup_behavior)

    def execute(self):
        self.scan_fields()
        # If scope if ALL_RECORDS, execute a Bulk API job to extract all records
        # If scope is QUERY, execute a Bulk API job to download a query with where_clause
        # If scope is DESCENDENTS, pull based on objects that look up to any already
        # extracted object.
        # If scope is SELECTED_RECORDS, and if `context` has any registered dependencies,
        # perform a query to extract those records by Id.

        if self.scope == ExtractionScope.ALL_RECORDS:
            query = 'SELECT {} FROM {}'.format(self.get_field_list(), self.sobjectname)

            self.context.logger.debug('%s: extracting all records using Bulk API query %s', self.sobjectname, query)
            self.perform_bulk_api_pass(query)
            return
        elif self.scope == ExtractionScope.QUERY:
            query = 'SELECT {} FROM {} WHERE {}'.format(self.get_field_list(), self.sobjectname, self.where_clause)

            self.context.logger.debug('%s: extracting filtered records using Bulk API query %s', self.sobjectname, query)
            self.perform_bulk_api_pass(query)
        elif self.scope == ExtractionScope.DESCENDENTS:
            self.context.logger.debug('%s: extracting descendent records based on lookups %s', self.sobjectname, ', '.join(self.descendent_lookups))

            for f in self.descendent_lookups:
                self.perform_lookup_pass(f)

        # Fall through to grab all dependencies registered with the context, or SELECTED_RECORDS
        # Note that if we're tracing self-lookups, the parent objects of all extracted records so far
        # will already be registered as dependencies.

        self.resolve_registered_dependencies()

        # If we have any self-lookups, we now need to iterate to handle them.
        if len(self.self_lookups) > 0 and self.self_lookup_behavior is SelfLookupBehavior.TRACE_ALL \
            and self.scope != ExtractionScope.ALL_RECORDS:
            # First we query up to the parents of objects we've already obtained (i.e. the targets of their lookups)
            # Then we query down to the children of all objects obtained.
            # Then we query parents and children again.
            # We repeat until we get back no new Ids, which indicates that all references have been resolved.

            # Note that the initial parent query is handled in the dependency pass above, so we start on children.

            self.context.logger.debug('%s: recursing to trace self-lookups', self.sobjectname)

            while True:
                before_count = len(self.context.get_extracted_ids(self.sobjectname))

                # Children
                for l in self.self_lookups:
                    self.perform_lookup_pass(l)

                # Parents
                self.resolve_registered_dependencies()

                after_count = len(self.context.get_extracted_ids(self.sobjectname))

                if before_count == after_count:
                    break

    def store_result(self, result):
        # Examine the received data to determine whether we have any cross-hierarchy lookups
        # or down-hierarchy dependencies to register

        field_map = self.context.get_field_map(self.sobjectname)
        sobject_list = self.context.get_sobject_list()

        # Add a dependency for the reference in each self lookup of this record.
        for l in self.self_lookups:
            if self.get_self_lookup_behavior_for_field(l) is not SelfLookupBehavior.TRACE_NONE and result[l] is not None:
                self.context.add_dependency(self.sobjectname, SalesforceId(result[l]))

        # Register any dependencies from dependent lookups
        # Note that a dependent lookup can *also* be a descendent lookup (e.g. Task.WhatId),
        # so we handle polymorphic lookups carefully
        for f in self.dependent_lookups:
            lookup_value = result[f]
            if lookup_value is not None:
                # Determine what sObject this Id looks up to
                # If this is a regular lookup, it's the target of the field, and is always dependent.
                # If this lookup is polymorphic, we have to determine it based on the Id itself,
                # and this value may actually be a cross-hierarchy reference or descendent reference.
                if len(field_map[f]['referenceTo']) > 1:
                    target_sobject = self.context.get_sobject_name_for_id(lookup_value)

                    if target_sobject not in sobject_list:
                        continue # Ignore references to objects not in our extraction.

                    # Determine if this is really a dependent connection, or if it's a descendent
                    # that should be handled below.
                    # The descendent code looks for cross-hierarchy references
                    if sobject_list.index(target_sobject) < sobject_list.index(self.sobjectname):
                        continue

                    # Otherwise, fall through to add a dependency
                else:
                    target_sobject = field_map[f]['referenceTo'][0]

                self.context.add_dependency(target_sobject, SalesforceId(lookup_value)) 
        
        # Check for cross-hierarchy lookup values:
        # references to records above us in the extraction hierarchy, but that weren't extracted already.
        for f in self.descendent_lookups:
            lookup_value = result[f]
            if len(field_map[f]['referenceTo']) == 1:
                target_sobject = field_map[f]['referenceTo'][0]
            else:
                target_sobject = self.context.get_sobject_name_for_id(lookup_value)
            
            if lookup_value not in self.context.get_extracted_ids(target_sobject):
                # This is a cross-hierarchy reference
                behavior = self.get_outside_lookup_behavior_for_field(f)

                if behavior is OutsideLookupBehavior.DROP_FIELD:
                    del result[f]
                elif behavior is OutsideLookupBehavior.INCLUDE:
                    continue
                elif behavior is OutsideLookupBehavior.ERROR:
                    self.errors.append(
                        '{} {} has an outside reference in field {} ({}), which is not allowed by the extraction configuration.'.format(
                            self.sobjectname,
                            result['Id'],
                            f,
                            result[f]
                        )
                    )

        # Finally, call through to the context to store this result.
        self.context.store_result(self.sobjectname, result)

    def resolve_registered_dependencies(self):
        pre_deps = self.context.get_dependencies(self.sobjectname).copy()
        self.perform_id_field_pass('Id', pre_deps)
        missing = self.context.get_dependencies(self.sobjectname).intersection(pre_deps)
        if len(missing) > 0:
            self.errors.append(
                'Unable to resolve dependencies for sObject {}. The following Ids could not be found: {}'.format(
                    self.sobjectname,
                    ', '.join([str(i) for i in missing])
                )
            )

    def perform_bulk_api_pass(self, query):
        bulk_proxy = self.context.get_bulk_proxy_object(self.sobjectname)

        results = bulk_proxy.query(query)

        for rec in results:
            self.store_result(rec)

    def perform_id_field_pass(self, id_field, id_set):
        query = 'SELECT {} FROM {} WHERE {} IN ({})'

        if len(id_set) == 0:
            return

        ids = id_set.copy()
        max_len = 4000 - len('WHERE {} IN ()'.format(self.get_field_list()))

        while len(ids) > 0:
            id_list = '\'' + str(ids.pop()) + '\''

            # The maximum length of the WHERE clause is 4,000 characters
            # Account for the length of the WHERE clause skeleton (above)
            # and iterate until we can't add another Id.
            while len(id_list) < max_len - 22 and len(ids) > 0:
                id_list += ', \'' + str(ids.pop()) + '\''

            results = self.context.connection.query_all(
                query.format(self.get_field_list(), self.sobjectname, id_field, id_list)
            )

            for rec in results.get('records'):
                self.store_result(rec)

    def perform_lookup_pass(self, field):
        self.perform_id_field_pass(
            field,
            self.context.get_sobject_ids_for_reference(self.sobjectname, field)
        )


class DataMapper(object):
    def __init__(self, field_name_mapping=None, field_transforms=None):
        self.field_name_mapping = field_name_mapping or {}
        self.field_transforms = field_transforms or {}

    def transform_record(self, record):
        return { self.transform_key(k): self.transform_value(k, record[k]) for k in record }

    def transform_key(self, k):
        return self.field_name_mapping.get(k, k)

    def transform_value(self, k, v):
        return functools.reduce(lambda x, f: f(x), self.field_transforms.get(k,[]), v)