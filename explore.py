#!/usr/bin/env python3

# Copyright (c) 2016 Tony Allan

# Explore information about employees.

import argparse
import configparser
from deputy import Deputy
from deputy import DeputyException
import json
import os
import sys

def get_config(config, section, item, missing=None):
    if section in config.sections():
        if item in config[section]:
            return config[section][item]
    return missing

def get_resource(resource_name, count=True, select=None):
    res = deputy.resource(resource_name)
    if count:
        print('Imported {0} records from resource {1}.'.format(len(res), resource_name))
    if select is not None:
        for id in res:
            r = res[id]
            if select in r:
                print('[{0}] {1}'.format(id,r[select]))
    return res

def extract(resource_name, resources, employees, find_id=None, count=True, attributes=[]):
    for resource_id in resources:
        resource = resources[resource_id]
        for attribute in attributes:
            a_id = resource[attribute]
            if a_id is not None:
                # CompanyPeriod has creator of -1.
                if a_id > 0:
                    if a_id in employees:
                        a_name = employees[a_id]['DisplayName']
                        if find_id is None:
                            print('  [{0}:{1}] {2}: {3} ({4})'.format(resource_name, resource_id, attribute, a_name, a_id))
                        else:
                            if a_id == find_id:
                                print('  [{0}:{1}] {2}: {3} ({4})'.format(resource_name, resource_id, attribute, a_name, a_id))
                    else:
                        print('  [{0}:{1}] {2}: *Employee not found* ({3})'.format(resource_name, resource_id, attribute, a_id))

def get_resource_and_extract(resource_name, employees, find_id=None, attributes=['Creator']):
    data = get_resource(resource_name)
    extract(resource_name, data, employees, find_id=find_id, attributes=attributes)
    return data


def pprint(data):
    print(json.dumps(data, sort_keys=True, indent=4, separators=(',', ': ')))



# ======================================================================================================================
if __name__ == '__main__':

    config_file = 'deputy.config'
    config = configparser.ConfigParser()
    config.read(os.path.expanduser(config_file))

    api_endpoint   = get_config(config, 'DEPUTY', 'api_endpoint')
    access_token   = get_config(config, 'DEPUTY', 'access_token')

    parser = argparse.ArgumentParser(
        description='Deputy Utilities',
        )
    parser.add_argument('-e', '--endpoint', help='API endpoint (override config file)',      default=api_endpoint)
    parser.add_argument('-a', '--token',    help='Access Token (override config file)',      default=access_token)
    parser.add_argument('-t', '--timeout',  help='HTTP timeout',                             default=20, type=int)
    parser.add_argument('-i', '--id',       help='employee_id',                              default=None, type=int)
    parser.add_argument('-l', '--list',     help='List all employees.',                      action='store_true')
    args = parser.parse_args()

    # All exceptions are fatal. API errors are displayed in the except statement.
    try:
        deputy = Deputy(args.endpoint, args.token, args.timeout)
        api_resp = deputy.api('me')
        print('DeputyVersion: {0} running as {1}.\n'.format(api_resp['DeputyVersion'], api_resp['Name']))

        if args.list:
            # fetch a list of all employees and list in alphabetical order
            employees = deputy.resource('Employee', sort='LastName')
            for id in employees:
                employee = employees[id]
                print('[{0}] {1}'.format(employee['Id'], employee['DisplayName']))
        else:
            # List created by eyeballing the Deputy API Docs — they are not always create on what a field contains
            # https://api-doc.deputy.com/Resources/Employee
            Employee = get_resource('Employee')
            Address =           get_resource_and_extract('Address', Employee, find_id=args.id)
            Category =          get_resource_and_extract('Category', Employee, find_id=args.id)
            Company =           get_resource_and_extract('Company', Employee, find_id=args.id)
            # CompanyPeriod has Creator always set to -1?
            CompanyPeriod =     get_resource_and_extract('CompanyPeriod', Employee, find_id=args.id)  
            Contact =           get_resource_and_extract('Contact', Employee, find_id=args.id)
            Country =           get_resource_and_extract('Country', Employee, find_id=args.id)
            CustomAppData =     get_resource_and_extract('CustomAppData', Employee, find_id=args.id, attributes=['Creator', 'Employee'])
            CustomField =       get_resource_and_extract('CustomField', Employee, find_id=args.id)
            CustomFieldData =   get_resource_and_extract('CustomFieldData', Employee, find_id=args.id)
            extract('Employee', Employee, Employee, find_id=args.id, attributes=['Id', 'Creator'])
            EmployeeAgreement = get_resource_and_extract('EmployeeAgreement', Employee, find_id=args.id, attributes=['Creator', 'EmployeeId'])
            EmployeeAgreementHistory = get_resource_and_extract('EmployeeAgreementHistory', Employee, find_id=args.id)
            EmployeeAppraisal = get_resource_and_extract('EmployeeAppraisal', Employee, find_id=args.id, attributes=['Creator', 'Employee'])
            # EmployeeAvailability
            # EmployeeHistory
            # EmployeePaycycle
            # EmployeePaycycleReturn
            # EmployeeRole
            # EmployeeSalaryOpunitCosting
            # EmployeeWorkplace
            # EmploymentCondition
            # EmploymentContract
            # EmploymentContractLeaveRules
            Event =             get_resource_and_extract('Event', Employee, find_id=args.id)
            Geo =               get_resource_and_extract('Geo', Employee, find_id=args.id)
            Journal =           get_resource_and_extract('Journal', Employee, find_id=args.id, attributes=['Creator', 'EmployeeId'])
            Kiosk =             get_resource_and_extract('Kiosk', Employee, find_id=args.id)
            # KpiBudget
            # KpiEntry
            # KpiMetric
            # KpiShiftReport
            Leave =             get_resource_and_extract('Leave', Employee, find_id=args.id, attributes=['Creator', 'Employee'])
            # LeavePayLine
            # LeaveRules
            Memo =              get_resource_and_extract('Memo', Employee, find_id=args.id)
            Noticeboard =       get_resource_and_extract('Noticeboard', Employee, find_id=args.id)
            # OperationalUnit
            # OpunitKpiMetricConfig
            # PayPeriod
            # PayRules
            Roster =            get_resource_and_extract('Roster', Employee, find_id=args.id, attributes=['Creator', 'ConfirmBy', 'Employee'])
            # [Exception: http_error] API resource/RosterOpen failed with 400 Bad Request.
            # RosterOpen =        get_resource_and_extract('RosterOpen', Employee, find_id=args.id, attributes=['Creator', 'Employee'])
            SalesData =         get_resource_and_extract('SalesData', Employee, find_id=args.id, attributes=['Creator', 'Employee'])
            Schedule =          get_resource_and_extract('Schedule', Employee, find_id=args.id)
            SmsLog =            get_resource_and_extract('SmsLog', Employee, find_id=args.id)
            # State
            # SystemUsageBalance
            # SystemUsageTracking
            # Task
            # TaskGroup
            # TaskGroupSetup
            # TaskOpunitConfig
            # TaskSetup
            Timesheet =         get_resource_and_extract('Timesheet', Employee, find_id=args.id, attributes=['Creator', 'Employee', 'Supervisor'])
            # TimesheetPayReturn
            # TrainingModule
            TrainingRecord =    get_resource_and_extract('TrainingRecord', Employee, find_id=args.id, attributes=['Creator', 'Employee'])


    except DeputyException as e:
        print(str(e))
        sys.exit(1)

