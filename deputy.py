#!/usr/bin/env python3

# Copyright (c) 2016 Tony Allan

# This script is all a bit of a hack.
# Some effort has been made to put communication with the Deputy api into the Deputy class.

# The script can be used to:
# - convert the CSV file from Synergetic to a Duputy CSV useful for importing employee's into Deputy.
# - add a year level for each student using the training module employee field to conveniently store the data.

import argparse
import configparser
import csv
import datetime
import http.client
import json
import os
import re
import sys
import urllib.parse



# Four classes as defined:
#   DeputyException for API errors
#   Deputy to provide API access
#   Printx to facilitate CSV output to stdout for some commands
#   College to encapsulate college specific functions:
#       parse_student_record
#       add_years_to_student_records

class DeputyException(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
    def __str__(self):
        if self.code == 'user_exit':
            return '\n{0}'.format(self.message)
        else:
            return '[Exception: {0}] {1}'.format(self.code, self.message)

class Deputy(object):
    """
    This is the only place the Deputy API is invoked.

    Assumes the following configuration data — usually just an argparse result (class argparse.Namespace):
        endpoint
        timeout
        token

    Raises a DeputyException if there is a problem, otherwise returns a decoded JSON response.
    """

    # Deputy columns needed for the Deputy bulk user reation upload file. This may change in the future.
    DEPUTY_COLS = ('First Name', 'Last Name', 'Time Card Number', 'Email', 'Mobile Number', 
        'Birth Date', 'Employment Date', 'Weekday', 'Saturday', 'Sunday', 'Public Holiday')

    def __init__(self, config):
        self.config = config

    def api(self, api, method='GET', data=None, dp_meta=False):
        """
        At least for Resource calls, api_resp is a list of results.

        The dp-meta-option header is passed if dp_meta is set. This adds additional resonse data.

        Returns the API data.
        """
        url = urllib.parse.urlparse(urllib.parse.urljoin(self.config.endpoint, api))
        try:
            conn = http.client.HTTPSConnection(url.hostname, url.port, timeout=self.config.timeout)
        except:
            raise DeputyException('invalid_url' 'Invalid URL: {0}'.format(self.config.endpoint))

        # format POST or PUT data as JSON and create the appripriate headers
        body = json.dumps(data)
        headers = {
            'Authorization':  'OAuth {0}'.format(self.config.token),
            'Content-type':   'application/json',
            'Accept':         'application/json',
            }
        if dp_meta is False:
            headers['dp-meta-option'] = 'none'
        try:
            conn.request(method, url.path, body, headers)
            resp = conn.getresponse()
        except KeyboardInterrupt:
            raise DeputyException('user_exit', 'Ctrl-C - User requested exit.')
        except socket.timeout:
            raise DeputyException('socket_timeout', 'Socket timeout for API {0}'.format(api))
        except socket.error as e:
            # This exception is raised for socket-related errors.
            raise DeputyException('sockey_error', 'Socket error ({0}) for API {1}.'.format(e.errno, api))
        #print(resp.status, resp.reason, dict(resp.getheaders()), resp.read())
        if resp.status == 302:
            raise DeputyException('unexpected_api', 'Unexpected API {0} response {1} {2} using API URL {3}.'.format(api, resp.status, resp.reason, url.geturl()))
        if resp.status != 200:
            raise DeputyException('http_error', 'API {0} failed with {1} {2}.'.format(api, resp.status, resp.reason))

        try:
            api_resp = json.loads(resp.read().decode('utf-8'))
        except ValueError:
            raise DeputyException('json_response_parse', 'Error parsing JSON API Response for {0}'.format(api))
        conn.close()
        return api_resp

    def resource(self, resource_name):
        """
        Get all resources where there might be more than 500 resources.
        Resource name is just 'Employee' or 'Contact' -- just the name of the resource.
        The result a list of records.

        See: http://api-doc.deputy.com/API/Resource_Calls -- /QUERY

        May raise DeputyException.

        PerhapsToDo: Add support for sort [FieldName : asc , FieldName:desc , …. ]
        """
        window = 500
        more = True
        position = 0
        result = []
        while more:
            data = {
                'search':{
                    'f1':{'field':'Id','type':'is','data':''}
                        }, 
                'start':position
                }
            api_resp = deputy.api('resource/{0}/QUERY'.format(resource_name), method='POST', data=data)
            result += api_resp
            if len(api_resp) == window:
                position += window
            else:
                more = False
        return result

    def resource_by_id(self, resource_name):
        """
        Get all resources where there might be more than 500 resources.
        Resource name is just 'Employee' or 'Contact' -- just the name of the resource.

        May raise DeputyException.

        The result always uses Id as the key.
        """
        window = 500
        more = True
        position = 0
        result = {}
        while more:
            data = {'search':{'f1':{'field':'Id','type':'is','data':''}}, 'start':position}
            api_resp = deputy.api('resource/{0}/QUERY'.format(resource_name), method='POST', data=data)
            for record in api_resp:
                result[record['Id']] = record
            if len(api_resp) == window:
                position += window
            else:
                more = False
        return result


    def employees(self):
        """
        Return a sorted list of Active employees:
            [{employee_id, employee_name, contact_id}]

        May raise DeputyException.
        """
        employees = []
        api_resp = self.resource('Employee')
        for employee in api_resp:
            # ignore inactive employee's. Those with a status=Discarded rather than Employed.
            if employee['Active'] is not True:
                continue
            employees.append({
                'employee_id':   employee['Id'],
                'employee_name': employee['DisplayName'],
                'contact_id':    employee['Contact'],
                'employee_role': employee['Role']
                })
        return employees

    def employee_by_id(self):
        employees = {}
        for employee in self.employees():
            #print(json.dumps(employee, sort_keys=True, indent=4, separators=(',', ': ')))
            employees[employee['employee_id']] = employee
        return employees

    def employee_by_email(self):
        contacts = self.resource_by_id('Contact')
        employees = {}
        for employee in self.employees():
            email_address = contacts[employee['contact_id']]['Email']
            employees[email_address] = employee
        return employees

    def employee_roles(self):
        """
        Get the name for each Role.
        e.g. Id:71 = Role:"Location Manager"

        Return a hash of Role indexed by the EmployeeRole Id.
        This is always a small table so a normal API call is used.

        May raise DeputyException.
        """
        employee_roles = {}
        api_resp = self.api('resource/EmployeeRole')
        for role in api_resp:
            employee_roles[role['Id']] = role['Role']
        return employee_roles

    # The remaining methods are College specific

    def years(self):
        """
        This is a college specific method to fetch the training module id labels.
        Returns something like:
        {   "Year1": 4,
            "Year2": 6,
            "Year3": 7  }

        May raise DeputyException.
        """
        api_resp = self.api('resource/TrainingModule')
        years = {}
        for tm in api_resp:
            if tm['Title'].startswith('Year'):
                years[tm['Title']] = tm['Id']
        return years

    def student_years(self):
        """
        This is a college specific method.
        Return a hash of year levels for each student who has a year assigned:
            [{employee_id:year_level}]
        Assumes only one year per student.

        May raise DeputyException.
        """
        # invert the list
        year_list = {}
        years = self.years()
        for year in years:
            year_list[years[year]] = year

        training_records = {}
        api_resp = self.api('resource/TrainingRecord')
        for record in api_resp:
            if record['Module'] in year_list:
                training_records[record['Employee']] = year_list[record['Module']]
        return training_records


class Printx(object):
    """
    This is a helper class to allows outout to be formated as text or a CSV record.
    """
    def __init__(self, title=None, csv_flag=False):
        #Create a writer on stdout if csv selected
        self.csv = csv_flag
        if self.csv:
            self.writer = csv.writer(sys.stdout, quoting=csv.QUOTE_MINIMAL)
        if title is not None:
            self.text(title)

    def text(self, text, *values):
        # if csv, write text to stderr because stdout is used for the csv output
        if self.csv:
            print(text.format(*values), file=sys.stderr)
        else:
            print(text.format(*values))

    def headers(self, *values):
        # only write a header if CSV output is required.
        if self.csv:
            self.writer.writerow(values)

    def data(self, text, *values):
        # write to CSV or normal text.
        if self.csv:
            self.writer.writerow(values)
        else:
            self.text(text, *values)


class College(object):
    """
    This class is just a wrapper for three functions used by the script:
        parse_csv — to read an input CSV row, perform fixups, and create a Deputy user creation CSV row.
        add_years_to_student_records — to add a student year level as a new TrainingRecord resource.
    """
    def __init__(self, deputy):
        self.deputy=deputy
        # fetch the date now so all timestamps are the same for this execution.
        self.today_iso = datetime.datetime.now().isoformat()

    def today(self):
        return self.today_iso

    def parse_student_record(self, row, include_mobile=False):
        """
        Parse a row from the input CSV file and create a row for the Deputy compatible user CSV file, 
        applying college specifc business rules.

        Returns a tuple (messages, row), where messages is an array of parse processing messages, and
        row is the Deputy output record.

        synergetic_csv                      deputy_csv
        ----------------------------------  -----------------------------
        ID
        Title
        Surname                             Last Name
        Given1
        Preferred                           First Name
        BirthDate
        Address1
        Address2
        Address3
        Suburb
        State
        PostCode
        Country
        StudentTertiaryCode
        Course                             -> used to create year level
        StudentLegalFullName
        CourseStatus
        FileSemester
        FileYear
        StudentCampus
        StudentBoarder
        Email
        NetworkLogin                        Time Card Number
        OccupEmail                          Email
        YearatUni                           -> used to create year level
        StudentPreviousSchool
        Description
        MobilePhoneActual                   Mobile Number

        Deputy fields not used:
            Birth Date / Employment Date / Weekday / Saturday / Sunday / Public Holiday

        Indicates Postgrad:
        1/2/3 Year 1,2 or 3 unless Course field suggests a higher degree.
        "Study Abroad & Exchange" do bursary.

        Exceptions:
        3 yes. Missing YearatUni for Mr Wayne Chen Zheng for course Biomedicine
        """
        messages = []

        first_name =  row['Preferred']
        last_name =   row['Surname']
        student_id =  row['NetworkLogin']
        email =       row['OccupEmail']
        course =      row['Course']
        year_at_uni = row['YearatUni']
        mobile =      row['MobilePhoneActual']
        name =        '{0} {1}'.format(first_name, last_name)

        # Fixup's to cater for poor quality and inconsistent input data.

        # Fix missing NetworkLogin (assume email is OK in this instance)
        if len(student_id) == 0:
            student_id = email.split('@')[0]
            messages.append('Missing NetworkLogin for {0}. Setting to {1} using email {2}.'.format(name, student_id, email))

        # exclude some users
        if student_id in exclude:
            messages.append('Excluded {0} ({1}) who is on the exclude list.'.format(name, student_id, course))
            return (messages, None)

        # exclude postgrads
        for e in exclude_postgrad:
            if e in course:
                messages.append('Excluded {0} ({1}) for Post Grad course {2}.'.format(name, student_id, course))
                return (messages, None)

        # year 1,2,3 assignment        
        try:
            if int(year_at_uni) > 3:
                messages.append('Excluded {0} ({1}), Year at Uni {2} > 3 in course {3}.'.format(name, student_id, year_at_uni, course))
                return (messages, None)
        except ValueError:
            messages.append('Missing YearatUni for {0} ({1}). Setting to 1.'.format(name, student_id, course))
            year_at_uni = '1'
        year = 'Year{0}'.format(year_at_uni)

        # Exception due to invalid data
        if student_id == 'wzheng':
            messages.append('Fixup for {0} ({1}). Setting year to 3.'.format(name, student_id))
            year = 'Year3'

        # fix Mobile phone number
        if len(mobile) == 0:
            messages.append('Missing phone number for {0} ({1}).'.format(name, student_id))
            mobile = None
        else:
            mobile = mobile.replace(' ', '')
            mobile = re.sub('^\+61', '0', mobile)
            mobile = re.sub('^61', '0', mobile)
            if mobile.startswith('00') or mobile.startswith('+'):
                messages.append('International phone number for {0} ({1}): {2}. Setting to Blank.'.format(name, student_id, mobile))
                mobile = ''
            else:
                # Excel sometimes drops the leading zero.
                if len(mobile) is 9:
                    mobile = '0' + mobile
                # An Australian mobile number must be 10 characters long.
                if len(mobile) is not 10:
                    messages.append('Incorrect mobile number for {0} ({1}): {2}. Setting to Blank.'.format(name, student_id, mobile))
                    mobile = ''
                else:
                    mobile = '{0} {1} {2}'.format(mobile[0:4],mobile[4:7], mobile[7:10])

        # fix email address
        if email_test is not None:
            if email_test not in email:
                messages.append('Incorrect {0} email address {1} ({2}): {3}. Fixing.'.format(email_test, name, student_id, email))
                if email_domain is not None:
                    email = '{0}@{1}'.format(student_id, email_domain)
                else:
                    email = None

        # create the new row
        new_row = {
            'first_name':       first_name,
            'last_name':        last_name,
            'student_id':       student_id,
            'email':            email,
            'year':             year,
            'mobile':           mobile
            }

        return (messages, new_row)

    def add_years_to_student_records(self, years, student_years, import_csv):
        """
        Add the student year level as a training module for each student found in the import_csv file.
        A training module is used because it is conveniently placed in the Deputy UI for Employee's.

        The year level will NOT BE ADDED if the student already has a year level assigned.

        student_years = {employee_id: year_text}. For example, year_text=Year2

        Returns an array of processing messages.

        May raise DeputyException.
        """
        messages = []

        in_csv  = open(import_csv)
        reader = csv.DictReader(in_csv)

        employees = self.deputy.employee_by_email()

        count = 0
        not_found_count = 0
        already_count = 0
        added_count = 0
        for in_row in reader:
            # parse record but discard any messages
            parsed_row = self.parse_student_record(in_row)[1]
            if parsed_row is None:
                continue
            email = parsed_row['email']
            name = '{0} {1}'.format(parsed_row['first_name'], parsed_row['last_name'])

            if email not in employees:
                messages.append('Not Found: {0} ({1})'.format(name, email))
                not_found_count += 1
                continue

            count += 1
            employee = employees[email]
            employee_id = employee['employee_id']

            year = parsed_row['year']

            # dont add year if one already exists
            if employee_id in student_years:
                already_count += 1
                continue

            training_module = years[year]
            messages.append('Student {0} ({1}) is in {2}'.format(name, employee_id, year))

            # Add training module Years1/2/3 for each student
            # TODO FIX the date...
            data = {
               'Employee': employee_id,
               'Module': training_module,
               'TrainingDate': self.today(),
               'Active': True
            }
            api_resp = deputy.api('resource/TrainingRecord', method='POST', data=data)
            added_count += 1

        messages.append('Processed {0} students.'.format(count))
        messages.append('{0} students not found in Deputy.'.format(not_found_count))
        messages.append('{0} students already had a year level set.'.format(already_count))
        messages.append('Added year level to {0} students.'.format(added_count))
        return messages


# ======================================================================================================================
if __name__ == '__main__':
    # all printing occurs here to allow the classes above to be independantly instantiated.

    config_file = 'deputy.config'
    config = configparser.ConfigParser()
    config.read(os.path.expanduser(config_file))

    def get_config(config, section, item, missing=None):
        if section in config.sections():
            if item in config[section]:
                return config[section][item]
        return missing

    api_endpoint   = get_config(config, 'DEPUTY', 'api_endpoint')
    access_token   = get_config(config, 'DEPUTY', 'access_token')
    import_csv     = get_config(config, 'IMPORT', 'import_csv', missing='import.csv')
    deputy_csv     = get_config(config, 'IMPORT', 'deputy_csv', missing='deputy.csv')
    email_test     = get_config(config, 'IMPORT', 'email_test')
    email_domain   = get_config(config, 'IMPORT', 'email_domain')

    if api_endpoint is None:
        print('Error. Missing configuration item api_endpoint.')
        sys.exit(1)
    if access_token is None:
        print('Error. Missing configuration item access_token.')
        sys.exit(1)

    # students who don't have to do any bursarys
    exclude = []
    if get_config(config, 'IMPORT', 'exclude') is not None:
        for u in get_config(config, 'IMPORT', 'exclude').split(','):
            exclude.append(u.strip())

    # post grads don't have to do it either, so exclude student if these strings are in their cource name
    exclude_postgrad = []
    if get_config(config, 'IMPORT', 'postgrad') is not None:
        for u in get_config(config, 'IMPORT', 'postgrad').split(','):
            exclude_postgrad.append(u.strip())
    
    # process the command line
    parser = argparse.ArgumentParser(
        description='Deputy Utilities',
        )
    parser.add_argument('-e', '--endpoint', help='API endpoint (override config file)',      default=api_endpoint)
    parser.add_argument('-a', '--token',    help='Access Token (override config file)',      default=access_token)
    parser.add_argument('--import_csv',     help='Import CSV (override config file)',        default=import_csv)
    parser.add_argument('--deputy_csv',     help='Deputy CSV output (override config file)', default=deputy_csv)
    parser.add_argument('-t', '--timeout',  help='HTTP timeout',          default=20, type=int)
    parser.add_argument('command',          help='command (e.g. status)', default='intro', nargs='?',
        choices=['intro', 'config', 'list', 'report', 'journal', 'user-csv', 'add-year', 'api', 'resource', 'test'])
    parser.add_argument('--api',            help='View API',              default='me')
    parser.add_argument('--resource',       help='View Response',         default='Employee')
    parser.add_argument('--mobile',         help='Include Mobile phone number in the Deputy CSV file', action='store_true')
    parser.add_argument('--csv',            help='Format output as CSV',  action='store_true')
    parser.add_argument('--hide_ok',        help='In report, hide if no problems.', action='store_true')
    args = parser.parse_args()

    # All exceptions are fatal. API errors are displayed in the except statement.
    try:
        p = Printx(csv_flag=args.csv)
        deputy = Deputy(args)
        api_resp = deputy.api('me')

        # class containg college specific functions
        college = College(deputy)

        if args.command == 'intro':
            p.text('DeputyVersion: {0} running as {1}.\n', api_resp['DeputyVersion'], api_resp['Name'])
            p.text('A script to invoke the Deputy API''s. Use --help to see a list of commands.')
            p.text('For more information, see https://github.com/tonyallan/deputy/\n')
            p.text('For a list of commands use --help')

        elif args.command == 'config':
            p.text('DeputyVersion: {0} running as {1}.\n', api_resp['DeputyVersion'], api_resp['Name'])
            p.text('Using config file ({0})', os.path.abspath(config_file))
            for section in config.sections():
                p.text('\n[{0}]', section)
                for item in config[section]:
                    p.text('    {0:14}= {1}', item, config[section][item])

        elif args.command == 'user-csv':
            in_csv  = open(args.import_csv)
            out_csv = open(args.deputy_csv, 'w')

            reader = csv.DictReader(in_csv)
            writer = csv.DictWriter(out_csv, fieldnames=deputy.DEPUTY_COLS)
            writer.writeheader()

            count =0
            year_count = {'Year1': 0, 'Year2': 0, 'Year3':0}
            for in_row in reader:
                (messages, parsed_row) = college.parse_student_record(in_row, args.mobile)
                if parsed_row is not None:
                    if len(messages) > 0:
                        p.text('\n'.join(messages))
                    new_row = {
                        'First Name':       parsed_row['first_name'],
                        'Last Name':        parsed_row['last_name'],
                        'Time Card Number': parsed_row['student_id'],
                        'Email':            parsed_row['email'],
                        'Mobile Number':    parsed_row['mobile'],
                        }
                    writer.writerow(new_row)
                    year_count[parsed_row['year']] += 1
                    count += 1

            p.text('Students in Year1: {Year1}; Year2: {Year2}; Year3: {Year3}'.format(**year_count))
            p.text('Processed {0} students.', count)

        elif args.command == 'add-year':
            p.text('Add year level as a TrainingRecord for each student.')
            p.text('Fetching years...')
            years = deputy.years()
            p.text('Fetching training records (for year)...')
            student_years = deputy.student_years()
            messages = college.add_years_to_student_records(years, student_years, import_csv)
            p.text('\n'.join(messages))

        elif args.command == 'list':
            p.text('List of Bursary Students and their year level and email.\n')
            p.headers('Name', 'Year', 'Email')
            p.text('Fetching employees...')
            students = deputy.employees()
            #student_roles = deputy.get_employee_roles()
            p.text('Fetching training records (for year)...')
            student_years = deputy.student_years()
            p.text('Fetching contact details...')
            contacts = deputy.resource_by_id('Contact')
            bursary_student_count = 0
            for student in students:
                name = student['employee_name']
                if student['employee_id'] in student_years:
                    year = student_years[student['employee_id']]
                else:
                    continue
                email_address = contacts[student['contact_id']]['Email']
                if year is not None:
                    p.data('{0} ({1}, {2})', name, year, email_address)
                    bursary_student_count += 1
            p.text('\nListed {0} Bursary Students out of {1} active Deputy users.', bursary_student_count, len(students))

        elif args.command == 'journal':
            p.text('Journal Entries.\n')
            p.headers('Date', 'Name', 'Email', 'Category', 'Comment', 'Creator')
            p.text('Fetching employees...')
            students = deputy.employee_by_id()
            p.text('Fetching journals...')
            journals = deputy.resource('Journal')
            p.text('Fetching contacts...')
            contacts = deputy.resource_by_id('Contact')
            for journal in journals:
                employee_id = journal['EmployeeId']
                name = students[employee_id]['employee_name']
                date = journal['Date'][0:10] # just the date
                comment = journal['Comment']
                if len(journal['Category']) > 0:
                    # assume only one used for now
                    category = journal['Category'][0]['Category']
                else:
                    category = ''
                email = contacts[students[employee_id]['contact_id']]['Email']
                creator = students[journal['Creator']]['employee_name']
                p.data('[{0}] {1} ({2}) [{3}] {4} (by {5})', date, name, email, category, comment, creator)

        elif args.command == 'report':
            p.text('Student compliance report.\n')
            # Fetch student and config data
            if get_config(config, 'REPORT', 'shifts_year1') is None:
                shift_obligations = None
            else:
                shift_obligations = {
                    'Year1': get_config(config, 'REPORT', 'shifts_year1'),
                    'Year2': get_config(config, 'REPORT', 'shifts_year2'),
                    'Year3': get_config(config, 'REPORT', 'shifts_year3')}  
            p.text('Fetching employees...')          
            student_list = deputy.employees()
            p.text('Fetching training records (for year)...')
            student_years = deputy.student_years()
            # setup our 'students' hash that will hold their roster data.
            bursary_student_count = 0
            non_bursary_student_count = 0
            year_count = {'Year1': 0, 'Year2': 0, 'Year3':0}
            students = {}
            for student in student_list:
                name = student['employee_name']
                employee_id = student['employee_id']
                if employee_id not in student_years:
                    non_bursary_student_count += 1
                    continue
                year = student_years[employee_id]
                if year is not None:
                    students[employee_id] = {
                        'name': name,
                        'year': year,
                        'rostered': 0,
                        'completed': 0,
                        'open': 0,
                        'timesheet': 0
                    }
                    if shift_obligations is not None:
                        students[employee_id]['obligation'] = int(shift_obligations[year])
                    bursary_student_count += 1
                    year_count[year] += 1                    

            # ignore Swat Vac Bursary's
            p.text('Fetching operational units (for locations)...')
            operational_units = deputy.resource_by_id('OperationalUnit')
            # In the UI it's called the Location Name.
            location_name = get_config(config, 'REPORT', 'location_name')

            # itterate through their timesheets and counting if TimeApproved=True and IsLeave=False
            p.text('Fetching timesheets...')
            timesheets = deputy.resource('Timesheet')
            for timesheet in timesheets:
                # ignore if there is no location or it's not a match
                if location_name is not None:
                    if operational_units[timesheet['OperationalUnit']]['CompanyName'] != location_name:
                        continue
                # make sure someone approved then
                if not timesheet['TimeApproved']:
                    continue
                # make sure they are not a leave timesheet
                if timesheet['IsLeave']:
                    continue
                employee_id = timesheet['Employee']
                if employee_id in students:     # ignore test data or shifts by non Year1/2/3 students
                    students[employee_id]['timesheet'] += 1

            # itterate through their rosters, counting rostered and completed shifts
            p.text('Fetching rosters...')
            rosters = deputy.resource('Roster')
            rostered_count = 0
            completed_count = 0
            open_count = 0
            for roster in rosters:
                # ignore if there is no location or it's not a match
                if location_name is not None:
                    if operational_units[roster['OperationalUnit']]['CompanyName'] != location_name:
                        continue
                # Count but don't ignore open shifts
                if roster['Open']:
                    open_count += 1
                employee_id = roster['Employee']
                timesheet = roster['MatchedByTimesheet']
                if employee_id in students:     # ignore test data or shifts by non Year1/2/3 students
                    students[employee_id]['rostered'] += 1
                    rostered_count += 1
                    if timesheet > 0:
                        students[employee_id]['completed'] += 1
                        completed_count += 1
                    if roster['Open']:
                        students[employee_id]['open'] += 1

            # headers
            if shift_obligations is None:
                p.headers('Name', 'Rostered', 'Open', 'Completed', 
                    'Timesheets', 'Issues')
            else:
                p.headers('Name', 'Year', 'Obligation', 'Rostered', 'Open', 'Completed', 
                    '% Rostered', '% Completed', 'Timesheets', 'Issues')

            # write out the sorted list of results with a percentage complete
            # loop using student_list because it is sorted and therefore the report will be sorted.
            hidden = 0
            for s in student_list: 
                issues = ''
                employee_id = s['employee_id']
                if employee_id in students:
                    student = students[employee_id]
                    if shift_obligations is None:
                        p.data('{0} / R:{1}  O:{2} C:{3} T:{4} / {5}', 
                            student['name'], student['rostered'], student['open'], 
                            student['completed'], student['timesheet'], issues)
                    else:
                        percentage_rostered = '{0:.0f}%'.format(((0.0+student['rostered'])/student['obligation'])*100.0)
                        if (0.0+student['rostered'])/student['obligation'] < 1:
                            issues = 'Incomplete roster. '
                        percentage_complete = '{0:.0f}%'.format(((0.0+student['completed'])/student['obligation'])*100.0)
                        if (0.0+student['completed'])/student['obligation'] < 1:
                            issues += 'Outstanding Shifts.'
                        # option to hide record where completed = 100%
                        show = True
                        if args.hide_ok:
                            if (0.0+student['completed'])/student['obligation'] >= 1:
                                show = False
                                hidden += 1
                        if show:
                            p.data('{0} ({1}): {2}, {3}, {4} {5} {6} {7} {8} {9}', 
                                student['name'], student['year'], student['obligation'], 
                                student['rostered'], student['open'], student['completed'], percentage_rostered, 
                                percentage_complete, student['timesheet'], issues)
            # and some summary info
            # active is Status=Employed
            p.text('\nListed {0} Bursary Students out of {1} active Deputy users. Excluded {2} non-bursary users.', 
                bursary_student_count, len(student_list), non_bursary_student_count)
            if shift_obligations is not None:
                p.text('Students in Year1: {0}; Year2: {1}; Year3: {2}; Total: {3}', 
                    year_count['Year1'], year_count['Year2'], year_count['Year3'], 
                    year_count['Year1']+year_count['Year2']+year_count['Year3'])
            p.text('Rosters {0}, rostered {1}, completed {2}, open {3}.', 
                len(rosters), rostered_count, completed_count, open_count)
            if args.hide_ok:
                p.text('{0} 100% completed records hidden.', hidden)

        elif args.command == 'api':
            # e.g. python3 deputy.py api --api resource/EmployeeRole
            p.text('Fetching api...{0}', args.api)
            api_resp = deputy.api(args.api)
            print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))
            print('{0} API records returned.'.format(len(api_resp)))

        elif args.command == 'resource':
            # e.g. python3 deputy.py resource --resource
            p.text('Fetching resource...{0}', args.resource)
            api_resp = deputy.resource(args.resource)
            print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))
            print('{0} Resource records returned.'.format(len(api_resp)))

        elif args.command == 'test':
            #pass
            #y = deputy.student_years()
            y = deputy.employee_by_id()
            print(json.dumps(y, sort_keys=True, indent=4, separators=(',', ': ')))
            print('{0} Resource records returned.'.format(len(y)))

            #p.text('Fetching rosters...')
            #rosters = deputy.get_resources('Roster')
            #for r in rosters:
            #    # "StartTimeLocalized": "2016-03-16T13:30:00+11:00",
            #    # if r['StartTimeLocalized'].startswith('2016-04-14T09:30'):
            #    # 674 = Lorraine JAFFER
            #    #if r['Employee'] == 439:
            #    #    print(json.dumps(r, sort_keys=True, indent=4, separators=(',', ': ')))
            #    if r['Comment'] is not None:
            #        if len(r['Comment']) > 0:
            #            print(json.dumps(r, sort_keys=True, indent=4, separators=(',', ': ')))

            #email_addresses = deputy.get_email()
            #print(json.dumps(email_addresses, sort_keys=True, indent=4, separators=(',', ': ')))
            #print(len(email_addresses))
            ##data = {'search':{'f1':{'field':'FirstName','type':'lk','data':'%Reb%'}}}
            ##data = {'search':{'f1':{'field':'FirstName','type':'eq','data':'Tony'}}}
            #data = {'search':{'f1':{'field':'Id','type':'is','data':''}}, 'start':500}
            #api_resp = deputy.api('resource/Contact/QUERY', method='POST', data=data)
            ##resp = deputy.last_response
            #print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))
            #print(len(api_resp))

            #print(json.dumps(deputy.get_years(), sort_keys=True, indent=4, separators=(',', ': ')))
            #data = {
            #   'Employee': 412,
            #   # OperationalUnit
            #   'KeyInt': 1,
            #   'KeyString': 'fsmith',
            #   'DocumentId': 'student_id',
            #   'Label': 'Student ID',
            #   'Permission': ''
            #}
            #api_resp = deputy.api('/customdata', method='PUT', data=data)
            #resp = deputy.last_response
            #print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))

            #data = {
            #   'intCompanyId': 1,
            #   'strFirstName': 'Fred',
            #   'strLastName': 'Smith',
            #   'strEmail': 'test@example.com',
            #   'intRoleId': 50,
            #   'strDob': '',
            #   'strMobilePhone': '0419 123 456'
            #}
            #api_resp = deputy.api('/addemployee', method='POST', data=data)
            #resp = deputy.last_response
            #print(resp.status, resp.reason, dict(resp.getheaders()), resp.read())
            #print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))

    except DeputyException as e:
        print(str(e))
        sys.exit(1)
    #except Exception as e:
    #    print(str(e))
    #    sys.exit(1)

    sys.exit(0)
