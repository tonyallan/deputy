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
import http.client
import json
import os
import re
import sys
import urllib.parse

# Deputy columns needed for upload file. This may change in the future.
deputy_cols = ['First Name', 'Last Name', 'Time Card Number', 'Email', 'Mobile Number', 'Birth Date', 'Employment Date', 'Weekday', 'Saturday', 'Sunday', 'Public Holiday']


class Deputy(object):
    def __init__(self, config):
        self.config = config
        self.last_response = None

    def api(self, api, method='GET', data=None, dp_meta=False):
        """
        At least for Resource calls, api_resp is a list of results.
        """
        url = urllib.parse.urlparse(urllib.parse.urljoin(self.config.endpoint, api))
        try:
            conn = http.client.HTTPSConnection(url.hostname, url.port, timeout=self.config.timeout)
        except:
            print ('Error. Invalid URL: {0}'.format(self.config.endpoint))
            sys.exit(1)

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
            print('\nCtrl-C - User requested exit.')
            exit(2)
        except socket.timeout:
            print('Error. Socket timeout for API {0}'.format(api))
            exit(2)
        except socket.error as e:
            # This exception is raised for socket-related errors.
            print('Error. Socket error ({0}) for API {1}.'.format(e.errno, api))
            exit(2)
        #print(resp.status, resp.reason, dict(resp.getheaders()), resp.read())
        if resp.status == 302:
            print('Error. Unexpected API {0} response {1} {2} using API URL {3}.'.format(api, resp.status, resp.reason, url.geturl()))
            exit(1)
        if resp.status != 200:
            print('Error. API {0} failed with {1} {2}.'.format(api, resp.status, resp.reason))
            exit(1)

        try:
            api_resp = json.loads(resp.read().decode('utf-8'))
        except ValueError:
            print('Error parsing JSON API Response for {0}'.format(api))
            api_resp = ''
        conn.close()
        #print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))
        return api_resp

    def get_resources(self, resource_name):
        """
        Get all resources where there might be more than 500 resources.
        Resource name is just 'Employee' or 'Contact' -- just the name of the resource.
        The result a list of records.

        See: http://api-doc.deputy.com/API/Resource_Calls -- /QUERY

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

    def get_resources_by_id(self, resource_name):
        """
        Get all resources where there might be more than 500 resources.
        Resource name is just 'Employee' or 'Contact' -- just the name of the resource.
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


    def get_employees(self):
        """
        Return a sorted list of active employees:
            [{employee_id, employee_name, contact_id}]
        """
        fetched_employees = {}
        api_resp = self.api('resource/Employee')
        # TODO: change to api_resp = self.get_resources('Employee')
        #print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))
        for employee in api_resp:
            Active = employee['Active']
            if Active is not True:
                continue
            sort = '{0}:{1}:{2}'.format(employee['LastName'].lower(), employee['FirstName'].lower(), employee['Id'])
            #role_id  = employee['Role']
            fetched_employees[sort]= {
                'employee_id':   employee['Id'],
                'employee_name': employee['DisplayName'],
                'contact_id':    employee['Contact'],
                'employee_role': employee['Role']
                }
        employees = []
        for e in sorted(fetched_employees.keys()):
            employees.append(fetched_employees[e])
        return employees

    def get_employee_roles(self):
        """
        Return a hash of roles:
            [{role_id:name}]
        """
        employee_roles = {}
        api_resp = self.api('resource/EmployeeRole')
        for role in api_resp:
            employee_roles[role['Id']] = role['Role']
        return employee_roles

    # The remaining methods are College specific

    def get_years(self):
        """
        This is a college specific method.
        Returns something like:
        {   "Year1": 4,
            "Year2": 6,
            "Year3": 7  }
        """
        api_resp = self.api('resource/TrainingModule')
        #print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))
        years = {}
        for tm in api_resp:
            if tm['Title'].startswith('Year'):
                years[tm['Title']] = tm['Id']
        return years

    def get_student_years(self):
        """
        This is a college specific method.
        Return a hash of year levels for each student:
            [{employee_id:year_level}]
        Assumes only one year per student.
        """
        # invert the list
        year_list = {}
        years = self.get_years()
        for year in years:
            year_list[years[year]] = year

        training_records = {}
        api_resp = self.api('resource/TrainingRecord')
        for record in api_resp:
            if record['Module'] in year_list:
                training_records[record['Employee']] = year_list[record['Module']]
            else:
                training_records[record['Employee']] = None
        return training_records


class Printx(object):
    def __init__(self, title=None, csv=False):
        self.text_fd = sys.stdout
        self.writer = None
        self.use_csv = False
        if csv:
            self.use_csv = True
            self.text_fd = sys.stderr
        if title is not None:
            self.text(title)

    def text(self, text, *values):
        print(text.format(*values), file=self.text_fd)

    def headers(self, *values):
        if self.use_csv:
            self.writer = csv.writer(sys.stdout, quoting=csv.QUOTE_MINIMAL)
            self.writer.writerow(values)

    def data(self, text, *values):
        if self.use_csv:
            self.writer.writerow(values)
        else:
            self.text(text, *values)


def parse_csv(row, include_mobile):
    """Parse Master student list, fixup data where needed, and create the deputy data.

    synergetic_csv                      deputy_csv
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

    #print(row['NetworkLogin'], row['OccupEmail'], row['Course'], row['YearatUni'])
    first_name =  row['Preferred']
    last_name =   row['Surname']
    student_id =  row['NetworkLogin']
    email =       row['OccupEmail']
    course =      row['Course']
    year_at_uni = row['YearatUni']
    mobile =      row['MobilePhoneActual']
    name =        '{0} {1}'.format(first_name, last_name)

    # Fix missing NetworkLogin (assume email is OK in this instance)
    if len(student_id) == 0:
        student_id = email.split('@')[0]
        print('Missing NetworkLogin for {0}. Setting to {1} using email {2}.'.format(name, student_id, email))

    # exclude some users
    if student_id in exclude:
        print('Excluded {0} ({1}) who is on the exclude list. '.format(name, student_id, course))
        return None

    # create Year1/2/3
    for e in exclude_postgrad:
        if e in course:
            print('Excluded {0} ({1}) for Post Grad course {2}.'.format(name, student_id, course))
            return None
    try:
        if int(year_at_uni) > 3:
            print('Excluded {0} ({1}), Year at Uni {2} > 3 in course {3}.'.format(name, student_id, year_at_uni, course))
            return None
    except ValueError:
        print('Missing YearatUni for {0} ({1}). Setting to 1.'.format(name, student_id, course))
        year_at_uni = '1'
    year = 'Year{0}'.format(year_at_uni)
    # Exception
    if student_id == 'wzheng':
        print('Fixup for {0} ({1}). Setting year to 3.'.format(name, student_id))
        year = 'Year3'
    #print('Student {0} is {1}'.format(student_id, year))

    # fix Mobile phone number
    mobile = mobile.replace(' ', '')
    if len(mobile) == 0:
        print('Missing phone number for {0} ({1}).'.format(name, student_id))
    else:
        mobile = re.sub('^\+61', '0', mobile)
        mobile = re.sub('^61', '0', mobile)
        if mobile.startswith('00') or mobile.startswith('+'):
            print('International phone number for {0} ({1}): {2}. Setting to Blank.'.format(name, student_id, mobile))
            mobile = ''
        else:
            # Excel sometimes drops the leading zero.
            if len(mobile) is 9:
                mobile = '0' + mobile
            if len(mobile) is not 10:
                print('Incorrect mobile number for {0} ({1}): {2}. Setting to Blank.'.format(name, student_id, mobile))
                mobile = ''
            else:
                mobile = '{0} {1} {2}'.format(mobile[0:4],mobile[4:7], mobile[7:10])

    # fix email address
    if email_test is not None:
        if email_test not in email:
            print('Incorrect {0} email address {1} ({2}): {3}. Fixing.'.format(email_test, name, student_id, email))
            if email_domain is not None:
                email = '{0}@{1}'.format(student_id, email_domain)
            else:
                email = None

    new_row = {
        'first_name':       first_name,
        'last_name':        last_name,
        'student_id':       student_id,
        'email':            email,
        'year':             year
        }
    if include_mobile:
        new_row['mobile'] = mobile
    return new_row

def add_years_to_student_records(years, import_csv):
    """
    Add the student year level as a training module for each student found in the import_csv file.
    A training module is used because it is conveniently placed in the Deputy UI for EMploye's.
    """
    in_csv  = open(import_csv)
    reader = csv.DictReader(in_csv)
    # employees[name] = employee id
    employees = {}
    api_resp = deputy.api('resource/Employee')
    for employee in api_resp:
        Active = employee['Active']
        if Active is not True:
            continue
        employee_id = employee['Id']
        DisplayName = employee['DisplayName']
        Contact = employee['Contact']
        Role = employee['Role']
        employees[DisplayName]= {
            'contact': Contact,
            'id':   employee_id
            }

    students = {}
    count = 0
    for in_row in reader:
        parsed_row = parse_csv(in_row)
        if parsed_row is None:
            continue

        name = '{0} {1}'.format(parsed_row['first_name'], parsed_row['last_name'])
        if name in employees:
            #print('Found:     {0}'.format(name))
            count += 1
        else:
            print('Not Found: {0}'.format(name))
            continue

        year = parsed_row['year']
        employee_id = employees[name]['id']
        training_module = years[year]
        print('Student {0} ({1}) is in {2}'.format(name, employee_id, year))

        # Add training module Years1/2/3 for each student
        data = {
           'Employee': employee_id,
           'Module': training_module,
           'TrainingDate': '2016-02-26',
           'Active': True
        }
        api_resp = deputy.api('resource/TrainingRecord', method='POST', data=data)
        #print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))

    print('Processed {0} students.'.format(count))

def get_config(config, section, item, missing=None):
    if section in config.sections():
        if item in config[section]:
            return config[section][item]
    return missing

# --------------------------------------------------------------------------------
if __name__ == '__main__':
    config_file = 'deputy.config'
    config = configparser.ConfigParser()
    config.read(os.path.expanduser(config_file))

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
    

    parser = argparse.ArgumentParser(
        description='Deputy Utilities',
        )
    parser.add_argument('-e', '--endpoint', help='API endpoint',          default=api_endpoint)
    parser.add_argument('-a', '--token',    help='Access Token',          default=access_token)
    parser.add_argument('--import_csv',     help='Import CSV',            default=import_csv)
    parser.add_argument('--deputy_csv',     help='Deputy CSV (output)',   default=deputy_csv)
    parser.add_argument('-t', '--timeout',  help='HTTP timeout',          default=20, type=int)
    parser.add_argument('command',          help='command (e.g. status)', default='intro', nargs='?',
        choices=['intro', 'config', 'list', 'report', 'journal', 'deputy-csv', 'add-year', 'view-api', 'test'])
    parser.add_argument('--api',            help='View API Response',     default='me')
    parser.add_argument('--mobile',         help='Incode Mobile in the Deputy CSV file', action='store_true')
    parser.add_argument('--csv',            help='Format output as CSV', action='store_true')
    parser.add_argument('--hide_ok',        help='In report, hide if no problems.', action='store_true')
    args = parser.parse_args()

    p = Printx(csv=args.csv)
    deputy = Deputy(args)
    api_resp = deputy.api('me')
    p.text('DeputyVersion: {0} running as {1}.', api_resp['DeputyVersion'], api_resp['Name'])

    if args.command == 'intro':
        print('\nA script to invoke the Deputy API''s. Use --help to see a list of commands.')

    elif args.command == 'config':
        print('Using config file ({0})'.format(config_file))
        for section in config.sections():
            print('\n' + section)
            for item in config[section]:
                print('    {0:14}= {1}'.format(item, config[section][item]))

    elif args.command == 'deputy-csv':
        in_csv  = open(args.import_csv)
        out_csv = open(args.deputy_csv, 'w')

        reader = csv.DictReader(in_csv)
        writer = csv.DictWriter(out_csv, fieldnames=deputy_cols)
        writer.writeheader()

        count =0
        year_count = {'Year1': 0, 'Year2': 0, 'Year3':0}
        for in_row in reader:
            parsed_row = parse_csv(in_row, args.mobile)
            if parsed_row is not None:
                new_row = {
                    'First Name':       parsed_row['first_name'],
                    'Last Name':        parsed_row['last_name'],
                    'Time Card Number': parsed_row['student_id'],
                    'Email':            parsed_row['email'],
                    'Mobile Number':    parsed_row['mobile'],
                    #'year':             parsed_row['year']
                    }
                writer.writerow(new_row)
                year_count[parsed_row['year']] += 1
                count += 1

        print('Students in Year1: {Year1}; Year2: {Year2}; Year3: {Year3}'.format(**year_count))
        print('Processed {0} students.'.format(count))

    elif args.command == 'add-year':
        years = deputy.get_years()
        add_years_to_student_records(years, import_csv)

    elif args.command == 'list':
        p.text('List of Bursary Students and their year level and email.\n')
        p.headers('Name', 'Year', 'Email')
        students = deputy.get_employees()
        #student_roles = deputy.get_employee_roles()
        student_years = deputy.get_student_years()
        contacts = deputy.get_resources_by_id('Contact')
        bursary_student_count = 0
        for student in students:
            name = student['employee_name']
            year = student_years[student['employee_id']]
            email_address = contacts[student['contact_id']]['Email']
            if year is not None:
                p.data('{0} ({1}, {2})', name, year, email_address)
                bursary_student_count += 1
        p.text('\nListed {0} Bursary Students out of {1} active Deputy users.', bursary_student_count, len(students))

    elif args.command == 'journal':
        p.text('Journal Entries.\n')
        p.headers('Date', 'Name', 'Email', 'Category', 'Comment', 'Creator')
        students = deputy.get_resources_by_id('Employee')
        journals = deputy.get_resources('Journal')
        contacts = deputy.get_resources_by_id('Contact')
        for journal in journals:
            employee_id = journal['EmployeeId']
            name = students[employee_id]['DisplayName']
            date = journal['Date'][0:10] # just the date
            comment = journal['Comment']
            if len(journal['Category']) > 0:
                # assume only one used for now
                category = journal['Category'][0]['Category']
            else:
                category = ''
            email = contacts[students[employee_id]['Contact']]['Email']
            creator = students[journal['Creator']]['DisplayName']
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
        student_list = deputy.get_employees()
        student_years = deputy.get_student_years()
        # setup our 'students' hash that will hold their roster data.
        bursary_student_count = 0
        non_bursary_student_count = 0
        year_count = {'Year1': 0, 'Year2': 0, 'Year3':0}
        students = {}
        for student in student_list:
            name = student['employee_name']
            employee_id = student['employee_id']
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
            else:
                non_bursary_student_count += 1

        # ignore Swat Vac Bursary's
        operational_units = deputy.get_resources_by_id('OperationalUnit')
        # In the UI it's called the Location Name.
        location_name = get_config(config, 'REPORT', 'location_name')

        # itterate through their timesheets and counting if TimeApproved=True and IsLeave=False
        timesheets = deputy.get_resources('Timesheet')
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
        rosters = deputy.get_resources('Roster')
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
                        issues = 'Incomplete roster.'
                    percentage_complete = '{0:.0f}%'.format(((0.0+student['completed'])/student['obligation'])*100.0)
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

    elif args.command == 'view-api':
        # e.g. python3 deputy.py --command view-api --api resource/EmployeeRole
        api_resp = deputy.api(args.api)
        print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))
        print('{0} Records returned.'.format(len(api_resp)))

    elif args.command == 'test':
        pass
        rosters = deputy.get_resources('Roster')
        for r in rosters:
            # "StartTimeLocalized": "2016-03-16T13:30:00+11:00",
            # if r['StartTimeLocalized'].startswith('2016-04-14T09:30'):
            # 674 = Lorraine JAFFER
            #if r['Employee'] == 439:
            #    print(json.dumps(r, sort_keys=True, indent=4, separators=(',', ': ')))
            if r['Comment'] is not None:
                if len(r['Comment']) > 0:
                    print(json.dumps(r, sort_keys=True, indent=4, separators=(',', ': ')))

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
