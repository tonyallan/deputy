#!/usr/bin/env python3

# Copyright (c) 2016-2019 Tony Allan

# This script is all a bit of a hack.
# Some effort has been made to put communication with the Deputy api into the Deputy class.

# The script can be used to:
# - convert the CSV file from Synergetic to a Duputy CSV useful for importing employee's into Deputy.
# - add a year level for each student using the training module employee field to conveniently store the data.

# https://www.deputy.com/api-doc/API

import argparse
import collections
import configparser
import csv
import datetime
import http.client
import json
import os
import re
import socket
import sys
import urllib.parse

import gspread
from oauth2client.service_account import ServiceAccountCredentials


def open_import_csv_reader(args):
    return  csv.DictReader(open(args.import_csv, encoding='utf-8-sig'))

# Five classes as defined:
#   Counter is a Dict subclass to simplify counters
#   DeputyException for API errors
#   Deputy to provide API access
#   Printx to facilitate CSV output to stdout for some commands
#   College, which extends Deputy and adds a number of college specific functions and methods.


class Counter(object):
    """
    A class of counters with a total and a set for each key.
    """
    def __init__(self):
        self.counters = collections.OrderedDict()
        self.data     = collections.OrderedDict()
        self.Desc     = collections.namedtuple('Desc', ['title', 'initial', 'increment'])
        self.Counter  = collections.namedtuple('Counter', ['id', 'title', 'count'])
        self.total    = collections.OrderedDict()

    def add_counter(self, id, title=None, initial=0, increment=1):
        self.counters[id] = self.Desc(title, initial, increment)
        self.total[id] = initial

    def count(self, key='', id=None, increment=None):
        if key not in self.data:
            self.data[key] = {}
            for c in self.counters:
                self.data[key][c] = self.counters[c].initial
        if increment is None:
            self.data[key][id] += self.counters[id].increment
            self.total[id]     += self.counters[id].increment
        else:
            self.data[key][id] += increment
            self.total[id]     += increment

    def get_count(self, key, id=None):
        if id is None:
            return self.data[key]
        else:
            return self.data[key][id]

    def get_total(self, id=None):
        if id is None:
            return self.total
        else:
            return self.total[id]

    def get_totals(self):
        result = []
        for id in self.counters:
            result.append(self.Counter(id, self.counters[id].title, self.total[id]))
        return result

    def __len__(self): 
        return len(self.data)

    def __repr__(self):
        return repr(self.data)

    def __getitem__(self, key):
        return self.data[key]

    def __iter__(self):
        return self.data.__iter__()

    def __contains__(self, item):
        return item in self.data

    def __delitem__(self, key):
        # totals are not reduced
        del self.data[key]


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
    This class and its subclasses are the only place the Deputy API is invoked.

    Raises a DeputyException if there is a problem, otherwise returns a decoded JSON response.
    """

    # Deputy columns needed for the Deputy bulk user creation upload file. This may change in the future.
    DEPUTY_COLS = ('First Name', 'Last Name', 'Time Card Number', 'Email', 'Mobile Number', 
        'Birth Date', 'Employment Date', 'Weekday', 'Saturday', 'Sunday', 'Public Holiday')

    def __init__(self, endpoint, token, timeout):
        self.endpoint = endpoint
        self.token    = token
        self.timeout  = timeout
        self.progress = Deputy.sample_progress


    @staticmethod
    def sample_progress(ptype, function, position):
        """
        A callback could be used to show progress if this class were used to generate web content. 
        student_report(), in particular, takes a while to gather its data.

        Set the callback with something like deputy.progress = your_function_name
        """
        #print('[Fetching {0}={1} {2}]'.format(ptype, function, position))
        pass


    def api(self, api, method='GET', data=None, dp_meta=False):
        """
        At least for Resource calls, api_resp is a list of results.

        The dp-meta-option header is passed if dp_meta is set. This adds additional resonse data.

        Returns the API data.
        """
        #self.progress('api', api, 0)
        #print('API', api)

        url = urllib.parse.urlparse(urllib.parse.urljoin(self.endpoint, api))
        try:
            conn = http.client.HTTPSConnection(url.hostname, url.port, timeout=self.timeout)
        except:
            raise DeputyException('invalid_url' 'Invalid URL: {0}'.format(self.endpoint))

        # format POST or PUT data as JSON and create the appripriate headers
        body = json.dumps(data)
        headers = {
            'Authorization':  'OAuth {0}'.format(self.token),
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
            resp = resp.read().decode('utf-8')
            api_resp = json.loads(resp)
        except ValueError:
            if len(resp) == 0:
                raise DeputyException('json_response_empty', 'Error parsing JSON API Response for {0} (zero length)'.format(api))
            else:
                raise DeputyException('json_response_parse', 'Error parsing JSON API Response for {0}'.format(api))
        conn.close()
        return api_resp


    def resource(self, resource_name, key='Id', sort='Id', join=[], select=None):
        """
        Get all resources where there might be more than 500 resources.
        Resource name is just 'Employee' or 'Contact' -- just the name of the resource.
    
        'key' is the dict key to fetch items from the dictionary.
        'sort' is they data key to sort by.
        'join' is a list of objects to include in the record, such as ['ContactObject']
        'select' is one or more additional search terms select=[(field, type, data)]
        The result an OrderedDict of namedtuple with the key as specified in the call order by 'sort'.

        QUERY is very powerful by only the simplest features are used here.
        See: http://api-doc.deputy.com/API/Resource_Calls -- /QUERY

        May raise DeputyException from the API call.
        """
        window = 500    # hardcoded in deputy's API.
        position = 0
        result = collections.OrderedDict()
        while True:
            self.progress('resource', resource_name, position)
            query = {
                'search': {
                    'f1':{'field':key, 'type':'is', 'data':''}
                        }, 
                'sort': {sort: 'asc'},
                'join' : join,
                'start': position
                }
            if select is not None:
                for s_field, s_type, s_data in select:
                    query['search'][s_field+'_'+str(s_data)] = {'field':s_field, 'type':s_type, 'data':s_data}
            api_resp = self.api('resource/{0}/QUERY'.format(resource_name), method='POST', data=query)
            for record in api_resp:
                result[record[key]] = record
            #print(len(api_resp), resource_name, position)
            if len(api_resp) == window:
                position += window
            else:
                break
        self.progress('resource', resource_name, len(result))
        return result


    def employees(self, key='Id', sort='LastName', join=[]):
        """
        Return OrderedDict of Active employees sorted by LastName.
        May raise DeputyException.
        """
        return self.resource('Employee', key=key, sort=sort, join=join, select=[('Active', 'eq',  True)])


    def employee_by_email(self):
        """
        Return an OrderedDict of employee's with email as the key.
        May raise DeputyException.
        """
        employees = self.employees(join=['ContactObject'])
        email_employees = collections.OrderedDict()
        for id in employees:
            employee = employees[id]
            email_address = employee['ContactObject']['Email']
            email_employees[email_address] = employee
        return email_employees


    def discarded_employees(self, key='Id', sort='LastName', join=[]):
        """
        Return OrderedDict of Discarded employees sorted by LastName.
        May raise DeputyException.
        """
        return self.resource('Employee', key=key, sort=sort, join=join, select=[('Active', 'eq',  False)])


    def discarded_employee_by_email(self):
        """
        Return an OrderedDict of Discarded employee's with email as the key.
        May raise DeputyException.
        """
        employees = self.discarded_employees(join=['ContactObject'])
        #print(json.dumps(employees, sort_keys=True, indent=4, separators=(',', ': ')))
        email_employees = collections.OrderedDict()
        for id in employees:
            employee = employees[id]
            try:
                email_address = employee['ContactObject']['Email']
            except KeyError:
                print('Could no process {} (id={})'.format(employee['DisplayName'], employee['Id']))
            email_employees[email_address] = employee
        return email_employees


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
        try:
            if self.csv:
                print(text.format(*values), file=sys.stderr)
            else:
                print(text.format(*values))
        except KeyError:
            print('[Keyerror]', text, str(*values))


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


    def stats(self, c):
        self.text('')
        for stat in c.stats:
            self.text('{0}: {1}', stat.text, stat.value)


class College(Deputy):
    """
    This class extends Deputy and adds a number of functions and methods.

    Static Methods:
        parse_student_record — to read an input CSV row, perform fixups, and create a Deputy user creation CSV row.
        add_years_to_student_records — to add a student year level as a new TrainingRecord resource.

    Methods:

    """


    def __init__(self, endpoint, token, timeout):
        # A function may also return some statistics.
        self.stats = []
        self.Stat = collections.namedtuple('Stat', ['id', 'text', 'value'])
        super().__init__(endpoint, token, timeout)


    @staticmethod
    def parse_student_record(row, include_mobile=False):
        """
        Function to parse a row from the input CSV file and create a row for the Deputy compatible 
        user CSV file, applying college specifc business rules.

        Returns a tuple (messages, row), where messages is an array of parse processing messages,
        and row is the Deputy output record.

        synergetic_csv                      deputy_csv
        ----------------------------------  -----------------------------
        Student ID
        Title
        Surname                             Last Name
        Given1
        Student Preferred                           First Name
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
        Boarder=Non Res Special             -> used to create year level
        StudentPreviousSchool
        Description
        MobilePhoneActual                   Mobile Number

        Deputy fields not used:
            Birth Date / Employment Date / Weekday / Saturday / Sunday / Public Holiday

        Indicates Postgrad:
        1/2/3/1NR Year 1,2,3,1NR unless Course field suggests a higher degree.
        "Study Abroad & Exchange" do bursary.

        Exceptions:
        3 yes. Missing YearatUni for Mr Wayne C Z for course Biomedicine
        """
        messages = []

        synergetic_id = row['Student ID'].strip()
        first_name =    row['Student Preferred'].strip()
        last_name =     row['Surname'].strip()
        student_id =    row['Network Login'].strip()
        email =         row['Trinity Email'].strip()
        course =        row['Course Description'].strip()
        year_at_uni =   row['UOMYear'].strip()
        boarder =       row['Boarder'].strip()
        mobile =        row['Mobile Phone'].strip()
        name =          '{0} {1}'.format(first_name, last_name).strip() # allow for students with a single name 

        # Fixup's to cater for poor quality and inconsistent input data.

        # Fix missing NetworkLogin (assume email is OK in this instance)
        if len(student_id) == 0:
            if len(email) ==0:
                student_id = None
                messages.append('Excluded {0} (Student ID: {1}) for Missing NetworkLogin and/or Trinity Email.'.format(name, synergetic_id))
                return (messages, None)
            else:
                student_id = email.split('@')[0]
                messages.append('Missing NetworkLogin for {0}. Setting to {1} using email {2}.'.format(name, student_id, email))

        # exclude some users (with potential include exceptions)
        if student_id in exclude_list:
            if student_id in include_list:
                print('include (1)', student_id)
            else:
                messages.append('Excluded {0} ({1}) who is on the exclude list.'.format(name, student_id, course))
                return (messages, None)

        if year_at_uni == 'Not Selected':
            messages.append('Excluded {0} ({1}), Year at Uni = Not Selected.'.format(name, student_id, year_at_uni, course))
            year = None
        else:

            # year_at_uni data contains "4 Years" and "1 Year"
            year_at_uni = year_at_uni.split(' ')[0]

            # year 1,2,3,1NR assignment        
            try:
                if boarder == 'Non Res Special':
                    year ='Year1NR'
                else:
                    if int(year_at_uni) > 3:
                        messages.append('Excluded {0} ({1}), Year at Uni {2} > 3 in course {3}.'.format(name, student_id, year_at_uni, course))
                        return (messages, None)
                    year = 'Year{0}'.format(year_at_uni)
            except ValueError:
                messages.append('Missing UOMYear for {0} ({1}). Setting to blank.'.format(name, student_id, course))
                year = None

        # exclude postgrads
        for e in exclude_postgrad:
            if e in course:
                messages.append('Excluded {0} ({1}) for Post Grad course {2}.'.format(name, student_id, course))
                return (messages, None)

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
                messages.append('Missing or incorrect {0} email address {1} ({2}): {3}. Fixing.'.format(email_test, name, student_id, email))
                if email_domain is not None:
                    email = '{0}@{1}'.format(student_id, email_domain)
                else:
                    email = None

        # create the new row
        new_row = {
            'synergetic_id':    synergetic_id,
            'first_name':       first_name,
            'last_name':        last_name,
            'student_id':       student_id,
            'email':            email,
            'year':             year,
            'mobile':           mobile
            }

        return (messages, new_row)


    def add_years_to_student_records(self, years, student_years, csv_reader):
        """
        Add the student year level as a training module for each student found in the import_csv file.
        A training module is used because it is conveniently placed in the Deputy UI for Employee's.

        The year level will not be changed if it is correct. It will be changed if it is different in 
        the CSV. It will be added if currently not specified.

        student_years = {employee_id: year_text}. For example, year_text=Year2

        Anyone excluded by parse_student_record() will NOT be updated, e.g. TCAC members and co-ordinators

        Returns an array of processing messages.

        May raise DeputyException.
        """
        messages = []

        employees = self.employee_by_email()

        count = 0
        not_found_count = 0
        already_count = 0
        added_count = 0
        for in_row in csv_reader:
            # parse record but discard any messages
            (messages, parsed_row) = self.parse_student_record(in_row)
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
            employee_id = employee['Id']

            year = parsed_row['year']

            if year is None:
                continue

            # dont add year if one already exists and is the correct year
            # print(employee_id, employee_id in student_years, student_years[employee_id][0], year)
            if employee_id in student_years:
                if student_years[employee_id][0] == year:
                    already_count += 1
                    continue
                else:
                    # remove incorrect year
                    api_resp = college.api('resource/TrainingRecord/{0}'.format(student_years[employee_id][1]), method='DELETE')
                    messages.append('Deleted old year: {0}'.format(api_resp))

            training_module = years[year]
            messages.append('Student {0} ({1}) is in {2}'.format(name, employee_id, year))

            # Add training module Years1/2/3/1NR for each student
            # TODO FIX the date...
            data = {
               'Employee': employee_id,
               'Module': training_module,
               'TrainingDate': datetime.datetime.now().isoformat(),
               'Active': True
            }
            api_resp = self.api('resource/TrainingRecord', method='POST', data=data)
            added_count += 1

        messages.append('Processed {0} students.'.format(count))
        messages.append('{0} students not found in Deputy.'.format(not_found_count))
        messages.append('{0} students already had a year level set.'.format(already_count))
        messages.append('Added year level to {0} students.'.format(added_count))
        return messages


    def delete_users(self, employees_by_email, student_years, csv_reader, use_csv=True, test=True):
        """
        Delete (i.e. set active to false) any student who is not in import_csv.

        The student to be deleted must:
        -- be an employee !
        -- must not be in input_csv (student_by_email)
        -- must have a Year1/Year2/Year3/Year1NR training record

        Returns an array of processing messages.

        May raise DeputyException.

        if use_csv is False then don't check students in the CSV file. Useful for end of year processing.
        """
        messages = []

        deleted_count = 0

        student_by_email = {}

        if use_csv:

            for in_row in csv_reader:
                # parse record but discard any messages
                (messages, parsed_row) = self.parse_student_record(in_row)
                if parsed_row is None:
                    continue

                email = parsed_row['email']
                name = '{0} {1}'.format(parsed_row['first_name'], parsed_row['last_name'])
                student_by_email[email] = name

        for employee_email in employees_by_email:
            if employee_email not in student_by_email: 
                student = employees_by_email[employee_email]
                student_id = student['Id']
                student_name = student['DisplayName']
                if student_id in student_years:
                    #print(student_id, student_name, student_years[student_id][0])
                    #print(json.dumps(student, sort_keys=True, indent=4, separators=(',', ': ')))
                    messages.append('Deleted student: {0} {1}'.format(student_name, student_id))
                    api_resp = college.api('resource/Employee/{0}'.format(student_id), method='POST', data={'Active': False})
                    #messages.append('API response: {0}'.format(api_resp))
                    deleted_count += 1

        messages.append('Processed {0} students.'.format(len(student_by_email)))
        messages.append('{0} students deleted.'.format(deleted_count))
        return messages


    def reinstate_users(self, employees_by_email, student_years, csv_reader, test=True):
        """
        Reinstate (i.e. set active to true) any student who is in import_csv.

        The student to be reinstated must:
        -- be an employee !
        -- must be in input_csv (student_by_email)
        -- must have a Year1/Year2/Year3/Year1NR training record

        Returns an array of processing messages.

        May raise DeputyException.
        """
        messages = []

        reinstated_count = 0

        # Get a list of students
        student_by_email = {}
        for in_row in csv_reader:
            # parse record but discard any messages
            (messages, parsed_row) = self.parse_student_record(in_row)
            if parsed_row is None:
                continue

            email = parsed_row['email']
            name = '{0} {1}'.format(parsed_row['first_name'], parsed_row['last_name'])
            student_by_email[email] = name

        for employee_email in employees_by_email:
            if employee_email in student_by_email: 
                student = employees_by_email[employee_email]
                student_id = student['Id']
                student_name = student['DisplayName']
                if student_id in student_years:
                    #print(student_id, student_name, student_years[student_id][0])
                    #print(json.dumps(student, sort_keys=True, indent=4, separators=(',', ': ')))
                    messages.append('Reinstated student: {0} {1}'.format(student_name, student_id))
                    api_resp = college.api('resource/Employee/{0}'.format(student_id), method='POST', data={'Active': True})
                    messages.append('API response: {0}'.format(api_resp))
                    reinstated_count += 1

        messages.append('Processed {0} students.'.format(len(student_by_email)))
        messages.append('{0} students reinstated.'.format(reinstated_count))
        return messages


    def years(self):
        """
        This is a college specific method to fetch the training module id labels.
        Returns something like:
        {   "Year1": 4,
            "Year2": 6,
            "Year3": 7  }

        May raise DeputyException.
        """
        api_resp = self.resource('TrainingModule')
        years = {}
        for tmi in api_resp:
            tm = api_resp[tmi]
            if tm['Title'] =='Year 3':
                # ignore historical error
                continue
            if tm['Title'].startswith('Year'):
                years[tm['Title']] = tm['Id']
        #self.stats.append(self.Stat('Training Modules', 'Training Modules', len(api_resp)))
        self.stats.append(self.Stat('years', 'Years', len(years)))
        return years


    def student_years(self):
        """
        This is a college specific method.
        Return a hash of year levels for each student (EmployeeId) who has a year assigned:
            [{employee_id:(year_level, training_record_id)}]
        Assumes only one year per student.

        May raise DeputyException.
        """
        # invert the list
        year_list = {}
        years = self.years()
        for year in years:
            year_list[years[year]] = year

        training_records = {}
        api_resp = self.resource('TrainingRecord')
        for record_i in api_resp:
            record = api_resp[record_i]
            if record['Module'] in year_list:
                training_records[record['Employee']] = (year_list[record['Module']], record['Id'])
        self.stats.append(self.Stat('training_records', 'Training Records', len(api_resp)))
        self.stats.append(self.Stat('training_records_wm', 'Training Records (with Module)', len(training_records)))
        return training_records


    def bursary_student_list(self, include_list):
        """
        List of Bursary Students.
        A Bursary Student is an employee who has a training record that includes Year1/2/3/1NR.
        """
        students = self.employees(join=['ContactObject'])
        student_years = self.student_years()        # e.g. for each student "709": ["Year3",7]

        Student = collections.namedtuple('Student', ['Id', 'Name', 'Year', 'Email'])
        result = []
        no_year_count = 0
        no_student_years = 0

        for student_id in students:
            student = students[student_id]
            name = student['DisplayName']
            email_address = student['ContactObject']['Email']
            if email_address.split('@')[0] in include_list:
                #print('include (2)', student_id)
                result.append(Student(student_id, name, '', email_address))
            else:
                if student_id in student_years:
                    year = student_years[student_id][0]
                else:
                    no_student_years += 1
                    continue
                if year is None:
                    no_year_count += 1
                else:
                    result.append(Student(student_id, name, year, email_address))

        self.stats.append(self.Stat('students', 'Active Deputy Employees', len(students)))
        self.stats.append(self.Stat('no_year_count', 'Employees with no Year', no_year_count))
        self.stats.append(self.Stat('no_student_years', 'Student not in student_years', no_student_years))
        self.stats.append(self.Stat('bursary_students', 'Bursary Students', len(result)))
        return result


    def deputy_journal_entries(self, start_date=None, end_date=None):
        """
        List of Journal Entries for active employee's.
        Journal entries are selected by Date (yyyy-mm-dd) between start_date and end_date.
        """
        employees = self.employees(join=['ContactObject'])
        journals = self.resource('Journal',
            select=[
                ('Date', 'ge',  start_date),
                ('Date', 'le',  end_date)
            ])
        Journal = collections.namedtuple('Journal', ['Date', 'Name', 'Email', 'Category', 'Comment', 'Creator'])
        result = []
        for journal_id in journals:
            journal = journals[journal_id]
            employee_id = journal['EmployeeId']
            if employee_id in employees:
                # only bother about employees that are still active
                employee = employees[employee_id]
                name = employee['DisplayName']
                date = journal['Date'][0:10] # just the date
                comment = journal['Comment']
                if len(journal['Category']) > 0:
                    # assume only one used for now
                    category = journal['Category'][0]['Category']
                else:
                    category = ''
                email = employee['ContactObject']['Email']
                if journal['Creator'] in employees:
                    # employee who created the record is still active
                    creator = employees[journal['Creator']]['DisplayName']
                else:
                    creator = ''
            result.append(Journal(date, name, email, category, comment, creator))
        self.stats.append(self.Stat('journal_entries', 'Journal Entries', len(result)))
        return result


    def student_timesheet_count(self, location_name, start_date=None, end_date=None):
        """
        Return a count of approved and non-approved, non-leave timesheets by employee_id.
        Timesheets are selected by Date (yyyy-mm-dd) between start_date and end_date.
        """
        timesheets = self.resource('Timesheet', join=['OperationalUnitObject'], 
            select=[
                ('Employee', 'ne',  0),
                ('Date', 'ge',  start_date),
                ('Date', 'le',  end_date)
            ])
        students = Counter()
        students.add_counter('timesheet', 'Timesheet')
        students.add_counter('approved_timesheet', 'Approved Timesheet')

        for id in timesheets:
            timesheet = timesheets[id]

            # ignore if there is no location or it's not a match
            if location_name is not None:
                if timesheet['OperationalUnitObject']['CompanyName'] != location_name:
                    continue

            # # make sure someone approved then
            # if not timesheet['TimeApproved']:
            #     continue
 
            # make sure they are not a leave timesheet
            if timesheet['IsLeave']:
                continue

            employee_id = timesheet['Employee']
            students.count(employee_id, 'timesheet')
            
            if timesheet['TimeApproved']:
                students.count(employee_id, 'approved_timesheet')

        return students


    def student_roster_count(self, location_name, start_date=None, end_date=None):
        """
        Return a count of approved, non-leave timesheets by Employee for the selected location.
        Employee may be for an inactive employee.
        Employee is ignored if it is zero.
        Rosters are selected by Date (yyyy-mm-dd) between start_date and end_date.
        """
        rosters = self.resource('Roster', join=['OperationalUnitObject'], 
            select=[
                ('Employee', 'ne',  0),
                ('Date', 'ge',  start_date),
                ('Date', 'le',  end_date)
            ])

        students = Counter()
        students.add_counter('rostered',  'Rosters Rostered')
        students.add_counter('completed', 'Rosters Completed')
        students.add_counter('open',      'Rosters Open')

        for id in rosters:
            roster = rosters[id]

            # ignore if there is no location or it's not a match
            if location_name is not None:
                if roster['OperationalUnitObject']['CompanyName'] != location_name:
                    continue

            employee_id = roster['Employee']
            timesheet = roster['MatchedByTimesheet']
            students.count(employee_id, 'rostered')

            if timesheet > 0:
                students.count(employee_id, 'completed')
            if roster['Open']:
                students.count(employee_id, 'open')

            # if employee_id == 1022:
            #     print(employee_id, students[1022])
            #     print(roster, '\n\n')

        self.stats.append(self.Stat('rosters',   'Rosters (for all locations)',   len(rosters)))
        self.stats.append(self.Stat('students',  'Rosters with Students',  len(students)))
        for total in students.get_totals():
            self.stats.append(self.Stat(*total))
        return students

    def student_report(self, obligation_by_year, location_name, include_list, start_date=None, end_date=None):
        """
        Student roster data.
        Timesheet data exists but is not currently used.
        Rosters are selected by Date between start_date and end_date.
        """
 
        # fetch 'Student', ['Id', 'Name', 'Year', 'Email']
        students = self.bursary_student_list(include_list)

        # count approved and non-approved, non-leave 'timesheet'
        student_timesheet_count = self.student_timesheet_count(location_name, start_date=start_date, end_date=end_date)

        # count 'rostered', 'completed', 'open' rosters
        student_roster_count = self.student_roster_count(location_name, start_date=start_date, end_date=end_date)
        roster_stats = self.stats
        #print(json.dumps(roster_stats, indent=4, separators=(',', ': ')))
        
        Report = collections.namedtuple('Report', ['Name', 'Year', 'Obligation', 'Rostered', 'Open', 'Completed', 
                'PercentRostered', 'PercentCompleted', 'Issues', 'Email', 'Timesheets', 'ApprovedTimesheets'])

        counts = Counter()
        counts.add_counter('Year1',                    'Students in Year 1')
        counts.add_counter('Year2',                    'Students in Year 2')
        counts.add_counter('Year3',                    'Students in Year 3')
        counts.add_counter('Year1NR',                  'Students in Year 1NR')
        counts.add_counter('roster_rostered_count',    'Rostered')
        counts.add_counter('roster_completed_count',   'Completed Rosters')
        counts.add_counter('roster_open_count',        'Open Rosters')
        counts.add_counter('timesheet_count',          'Timesheets')
        counts.add_counter('approved_timesheet_count', 'Approved Timesheets')

        # write out the sorted list of results with a percentage complete
        # loop using student_list because it is sorted and therefore the report will be sorted.
        result = []
        for student in students:
            if student.Id in student_roster_count:
                src = student_roster_count[student.Id]
            else:
                src = {'rostered': 0, 'completed': 0, 'open': 0}

            if student.Id in student_timesheet_count:
                stc = student_timesheet_count[student.Id]
            else:
                stc = {'approved_timesheet': 0, 'timesheet': 0}

            counts.count(id='roster_rostered_count',    increment=src['rostered'])
            counts.count(id='roster_completed_count',   increment=src['completed'])
            counts.count(id='roster_open_count',        increment=src['open'])
            counts.count(id='timesheet_count',          increment=stc['timesheet'])
            counts.count(id='approved_timesheet_count', increment=stc['approved_timesheet'])

            if student.Email.split('@')[0] in include_list:
                obligation = 0
            else:
                try:
                    obligation = int(obligation_by_year[student.Year])
                except KeyError:
                    print('Year Level data error ({}) for {}'.format(student.Year, student.Name))
                    print('Fix the error before proceeding.')
                    sys.exit(1)
                counts.count(id=student.Year)
                issues = ''

            if student.Email.split('@')[0] in include_list:
                percentage_rostered = ''
                percentage_complete = ''
            else:
                percentage_rostered = '{0:.0f}%'.format(((0.0+src['rostered'])/obligation)*100.0)
                if (0.0+src['rostered'])/obligation < 1:
                    issues = 'Incomplete roster. '
                percentage_complete = '{0:.0f}%'.format(((0.0+src['completed'])/obligation)*100.0)
                if (0.0+src['completed'])/obligation < 1:
                    issues += 'Outstanding Shifts.'

            result.append(Report(student.Name, student.Year, obligation, 
                src['rostered'], src['open'], src['completed'], percentage_rostered, 
                percentage_complete, issues, student.Email, stc['timesheet'], stc['approved_timesheet']))

        # and some summary info
        self.stats.append(self.Stat('student_bursary', 'Bursary Students', len(students)))
        self.stats.append(self.Stat('student_timesheet', 'Students with Timesheets', len(student_timesheet_count)))
        self.stats.append(self.Stat('student_roster', 'Students with Rosters', len(student_roster_count)))
        for total in counts.get_totals():
            self.stats.append(self.Stat(*total))
        return result


def sync_with_sheet(endpoint, token, timeout, sheet, shift_obligations, location_name, include_list, start, end):
    college = College(endpoint, token, timeout)

    worksheet_tally = sheet.worksheet('Tally')
    worksheet_stats = sheet.worksheet('Stats')

    header = worksheet_tally.row_values(1)

    email_col = header.index('Trinity Email') + 1
    email_col_values = worksheet_tally.col_values(email_col)[1:]

    #status_col = header.index('Status') + 1
    uni_year_col      = header.index('Uni Year') + 1
    obligation_col    = header.index('Obligation') + 1
    booked_col        = header.index('Booked') + 1
    completed_col     = header.index('Completed') + 1
    timesheets_col    = header.index('Timesheets') + 1
    approved_timesheets_col = header.index('Approved Timesheets') + 1

    students = {}
    email_address_mismatch = 0
    for student in college.student_report(shift_obligations, location_name, include_list, start_date=start, end_date=end):
        if student.Email in email_col_values:
            students[student.Email] = student
        else:
            print('Email address mismatch', student.Name, student.Email)
            email_address_mismatch += 1

    uni_year_list   = []
    obligation_list = []
    booked_list     = []
    completed_list  = []
    timesheets_list = []
    approved_timesheets_list = []

    row = 2     # 1 offset and skip header row
    processed_students = 0
    not_processed_students = 0

    for email in email_col_values:
        if email in students:
            student = students[email]
            uni_year_list.append(gspread.models.Cell(row, uni_year_col, value=student.Year))
            obligation_list.append(gspread.models.Cell(row, obligation_col, value=student.Obligation))
            booked_list.append(gspread.models.Cell(row, booked_col, value=student.Rostered))
            completed_list.append(gspread.models.Cell(row, completed_col, value=student.Completed))
            timesheets_list.append(gspread.models.Cell(row, timesheets_col, value=student.Timesheets))
            approved_timesheets_list.append(gspread.models.Cell(row, approved_timesheets_col, value=student.ApprovedTimesheets))
            processed_students += 1
        else:
            uni_year_list.append(gspread.models.Cell(row, uni_year_col, value=''))
            obligation_list.append(gspread.models.Cell(row, obligation_col, value=''))
            booked_list.append(gspread.models.Cell(row, booked_col, value=''))
            completed_list.append(gspread.models.Cell(row, completed_col, value=''))
            timesheets_list.append(gspread.models.Cell(row, timesheets_col, value=''))
            approved_timesheets_list.append(gspread.models.Cell(row, approved_timesheets_col, value=''))
            not_processed_students += 1

        row += 1

    #print('Processed rows:', row - 2)
    worksheet_tally.update_cells(uni_year_list)
    worksheet_tally.update_cells(obligation_list)
    worksheet_tally.update_cells(booked_list)
    worksheet_tally.update_cells(completed_list)
    worksheet_tally.update_cells(timesheets_list)
    worksheet_tally.update_cells(approved_timesheets_list)

    last_updated_cell = worksheet_stats.find('Processed')
    worksheet_stats.update_cell(last_updated_cell.row, last_updated_cell.col + 1, processed_students)
    #print('Processed Students', processed_students)

    # last_updated_cell = worksheet_stats.find('Included')
    # worksheet_stats.update_cell(last_updated_cell.row, last_updated_cell.col + 1, len(include_list))
    # print('Included Students', len(exclude_list))

    # last_updated_cell = worksheet_stats.find('Excluded')
    # worksheet_stats.update_cell(last_updated_cell.row, last_updated_cell.col + 1, len(exclude_list))
    # print('Excluded Students', len(include_list))

    # last_updated_cell = worksheet_stats.find('Postgrad')
    # worksheet_stats.update_cell(last_updated_cell.row, last_updated_cell.col + 1, len(exclude_postgrad))
    # print('Postgrad Students', len(exclude_postgrad))

    last_updated_cell = worksheet_stats.find('Not Processed')
    worksheet_stats.update_cell(last_updated_cell.row, last_updated_cell.col + 1, not_processed_students)
    #print('Not Processed', not_processed_students)

    last_updated_cell = worksheet_stats.find('Email address mismatch')
    worksheet_stats.update_cell(last_updated_cell.row, last_updated_cell.col + 1, email_address_mismatch)
    #print('Email address mismatch', email_address_mismatch)

    last_updated_cell = worksheet_stats.find('Last updated UTC')
    last_updated_value = datetime.datetime.utcnow().isoformat().split('.')[0]
    worksheet_stats.update_cell(last_updated_cell.row, last_updated_cell.col + 1, last_updated_value)
    #print('Last updated', last_updated_value)

    return {'processed_rows':row - 2, 
            'processed_students':processed_students, 
            'not_processed_students':not_processed_students,
            'email_address_mismatch':email_address_mismatch,
            'last_updated':last_updated_value}


# ======================================================================================================================
if __name__ == '__main__':
    # all printing occurs here to allow the classes above to be independantly instantiated.

    config_file = '~/deputy.config'
    config = configparser.ConfigParser()
    config.read(os.path.expanduser(config_file))

    def get_config(config, section, item, missing=None, manditory=False):
        if section in config.sections():
            if item in config[section]:
                return config[section][item]
        if manditory:
            print('[{}] {} not specified. Configure {}.'.format(section, item, config_file))
            sys.exit(9)
        else:
            return missing

    import_csv     = get_config(config, 'IMPORT', 'import_csv', missing='import.csv')
    deputy_csv     = get_config(config, 'IMPORT', 'deputy_csv', missing='deputy.csv')
    email_test     = get_config(config, 'IMPORT', 'email_test')
    email_domain   = get_config(config, 'IMPORT', 'email_domain')

    google_sheet_id             = get_config(config, 'SYNC', 'google_sheet_id')
    service_account_credentials = get_config(config, 'SYNC', 'service_account_credentials')


    # students who don't have to do any bursaries
    exclude_list = []
    if get_config(config, 'IMPORT', 'exclude') is not None:
        for u in get_config(config, 'IMPORT', 'exclude').split(','):
            exclude_list.append(u.strip())

    # students who do have to do  bursaries but would otherwise be excluded
    include_list = []
    if get_config(config, 'IMPORT', 'include') is not None:
        for u in get_config(config, 'IMPORT', 'include').split(','):
            include_list.append(u.strip())

    # post grads don't have to do it either, so exclude student if these strings are in their cource name
    exclude_postgrad = []
    if get_config(config, 'IMPORT', 'postgrad') is not None:
        for u in get_config(config, 'IMPORT', 'postgrad').split(','):
            exclude_postgrad.append(u.strip())
    
    # process the command line
    parser = argparse.ArgumentParser(description='Deputy Reporting and Utilities')
    parser.add_argument('-e', '--endpoint', help='API endpoint (override config file)',
        default=get_config(config, 'DEPUTY', 'api_endpoint', manditory=True))
    parser.add_argument('-a', '--token',    help='Access Token (override config file)',
        default=get_config(config, 'DEPUTY', 'access_token', manditory=True))
    parser.add_argument('--import_csv',     help='Import CSV (override config file)',
        default=import_csv)
    parser.add_argument('--deputy_csv',     help='Deputy CSV output (override config file)',
        default=deputy_csv)
    parser.add_argument('-t', '--timeout',  help='HTTP timeout',
        default=20, type=int)
    parser.add_argument('command',          help='command (e.g. status)',
        default='intro', nargs='?',
        choices=['intro', 'config', 'list', 'report', 'sync', 'journal', 'user-csv', 'add-year', 
                 'delete-users', 'delete-123-users', 'reinstate-users', 'api', 'resource', 'rd', 'rc', 'test'])
    parser.add_argument('--api',            help='View API',
        default='me')
    parser.add_argument('--resource',       help='View Response',
        default='Employee')
    parser.add_argument('--mobile',         help='Include Mobile phone number in the Deputy CSV file', action='store_true')
    parser.add_argument('--csv',            help='Format output as CSV',  action='store_true')
    parser.add_argument('--hide_ok',        help='In report, hide if no problems.', action='store_true')
    parser.add_argument('--start',          help='Start date for date based resources',
        default=get_config(config, 'REPORT', 'start_date', missing=None))
    parser.add_argument('--end',            help='End date for date based resources',
        default=get_config(config, 'REPORT', 'end_date', missing=None))
    args = parser.parse_args()

    # All exceptions are fatal. API errors are displayed in the except statement.
    try:
        p = Printx(csv_flag=args.csv)
        #deputy = Deputy(args.endpoint, args.token, args.timeout)
        college = College(args.endpoint, args.token, args.timeout)
        api_resp = college.api('me')        


        if args.command == 'intro':
            # Print helpful documentation
            p.text('DeputyVersion: {0} running as {1}.\n', api_resp['DeputyVersion'], api_resp['Name'])
            p.text('A script to invoke the Deputy API''s. Use --help to see a list of commands.')
            p.text('For more information, see https://github.com/tonyallan/deputy/\n')
            p.text('For a list of commands use --help')


        elif args.command == 'config':
            # List the contents of the configuration file (usually just a test to see if the config file can be read)
            p.text('DeputyVersion: {0} running as {1}.\n', api_resp['DeputyVersion'], api_resp['Name'])
            p.text('Using config file ({0})', os.path.abspath(config_file))
            for section in config.sections():
                p.text('\n[{0}]', section)
                for item in config[section]:
                    p.text('    {0:14}= {1}', item, config[section][item])


        elif args.command == 'user-csv':
            # Read from `import_csv` and write to `deputy.csv` in the correct format to allow bulk People creation.
            # UTF8 sig -- https://stackoverflow.com/questions/17912307/u-ufeff-in-python-string
            out_csv = open(args.deputy_csv, 'w', newline='')

            # get a list of student email addresses so we can remove already added users
            email_list = []
            for s in college.bursary_student_list(include_list):
                email_list.append(s.Email)

            reader = open_import_csv_reader(args)
            writer = csv.DictWriter(out_csv, fieldnames=college.DEPUTY_COLS)
            writer.writeheader()

            count = 0
            ignored = 0
            year_count = {'Year1': 0, 'Year2': 0, 'Year3':0, 'Year1NR': 0}
            for in_row in reader:
                try:
                    (messages, parsed_row) = college.parse_student_record(in_row, args.mobile)
                except KeyError as e:
                    sys.exit(f'Fatal Error. Missing import_csv header row: {e}. Check for extra space characters.')
                # parsed_row contains: first_name, last_name, student_id (i.e. NetworkLogin), email, year, mobile
                if len(messages) > 0:
                   p.text('\n'.join(messages))
                if parsed_row is not None:
                    if parsed_row['email'] in email_list:
                        #p.text('Ignoring user already in deputy: {0} {1} ({2})', parsed_row['first_name'], parsed_row['last_name'], parsed_row['email'])
                        #ignored += 1
                        continue
                    if parsed_row['year'] is None:
                        #p.text('Ignoring user with missing UOMYear: {0} {1} ({2})', parsed_row['first_name'], parsed_row['last_name'], parsed_row['email'])
                        #ignored += 1
                        continue
                    if len(parsed_row['student_id']) == 0:  # i.e. NetworkLogin
                        p.text('Ignoring user without a NetworkLogin: {0} {1} ({2})', parsed_row['first_name'], parsed_row['last_name'], parsed_row['email'])
                        ignored += 1
                        continue
                    new_row = {
                        'First Name':       parsed_row['first_name'],
                        'Last Name':        parsed_row['last_name'],
                        'Time Card Number': parsed_row['student_id'],
                        'Email':            parsed_row['email'],
                        'Mobile Number':    '', #parsed_row['mobile'], ## SMS messages cost too much so don't add a phone number.
                        }
                    writer.writerow(new_row)
                    year_count[parsed_row['year']] += 1
                    count += 1

            p.text('Students in Year1: {Year1}; Year2: {Year2}; Year3: {Year3}; Year1NR: {Year1NR}'.format(**year_count))
            p.text('Ignored {0} students.', ignored)
            p.text('Processed {0} students.', count)


        elif args.command == 'add-year':
            p.text('Add (or update) year level as a TrainingRecord for each student.')
            p.text('Fetching years...')
            years = college.years()
            p.text('Fetching training records (for year)...')
            student_years = college.student_years()
            messages = college.add_years_to_student_records(years, student_years, open_import_csv_reader(args))
            p.text('\n'.join(messages))


        elif args.command == 'delete-users':
            p.text('Remove students not in import_csv.')
            p.text('Fetching employee records...')
            students = college.employee_by_email()
            p.text('Fetching training records (for year)...')
            student_years = college.student_years()
            messages = college.delete_users(students, student_years, open_import_csv_reader(args), use_csv=True)
            # ToDo: fix KeyError: "'EmergencyAddress'" in the line below @line 261
            # ToDo: fix KeyError: "'PostalAddress'"
            # Todo: fix KeyError: "'Id'"
            p.text('\n'.join(messages))


        elif args.command == 'delete-123-users':
            p.text('Remove all users with a training record that includes Year1/2/3/1NR.')
            p.text('Fetching employee records...')
            students = college.employee_by_email()
            p.text('Fetching training records (for year)...')
            student_years = college.student_years()
            messages = college.delete_users(students, student_years, open_import_csv_reader(args), use_csv=False)
            p.text('\n'.join(messages))


        elif args.command == 'reinstate-users':
            p.text('Reinstate previously discarded students in import_csv.')
            p.text('Fetching employee records...')
            students = college.discarded_employee_by_email()
            p.text('Fetching training records (for year)...')
            student_years = college.student_years()
            messages = college.reinstate_users(students, student_years, open_import_csv_reader(args))
            # ToDo: fix KeyError: "'EmergencyAddress'" in the line below @line 261
            # ToDo: fix KeyError: "'PostalAddress'"
            p.text('\n'.join(messages))


        elif args.command == 'list':
            # For all Active employee's, show alphabetically: Name, Year and Email. 
            # Year will be blank if Training doesn't contain Year1, Year2 or Year3, Year1NR.
            p.text('List of Bursary Students and their year level and email.\n')
            p.headers('Id', 'Name', 'Year', 'Email')
            for s in college.bursary_student_list(include_list):
                p.data('[{0}] {1} ({2}, {3})', s.Id, s.Name, s.Year, s.Email)
            p.stats(college)


        elif args.command == 'journal':
            p.text('Journal Entries ({} to {}).\n'.format(args.start, args.end))
            p.headers('Date', 'Name', 'Email', 'Category', 'Comment', 'Creator')
            for e in college.deputy_journal_entries(start_date=args.start, end_date=args.end):
                p.data('[{0}] {1} ({2}) [{3}] {4} (by {5})', e.Date, e.Name, e.Email, e.Category, e.Comment, e.Creator)
            p.stats(college)


        elif args.command == 'report':
            p.text('Student compliance report ({} to {}).\n'.format(args.start, args.end))

            p.headers('Name', 'Year', 'Obligation', 'Rostered', 'Open', 'Completed', 
                '% Rostered', '% Completed', 'Issues') # removed for now 'Timesheets'

            # Fetch student and config data
            if get_config(config, 'REPORT', 'shifts_year1') is None:
                shift_obligations = None
            else:
                shift_obligations = {
                    'Year1':    get_config(config, 'REPORT', 'shifts_year1'),
                    'Year2':    get_config(config, 'REPORT', 'shifts_year2'),
                    'Year3':    get_config(config, 'REPORT', 'shifts_year3'),
                    'Year1NR':  get_config(config, 'REPORT', 'shifts_year1_nr')}  
            location_name  = get_config(config, 'REPORT', 'location_name')
            for student in college.student_report(shift_obligations, location_name, include_list, start_date=args.start, end_date=args.end):
                p.data('{0} ({1}): {2}, {3}, {4} {5} {6} {7} {8}', *student)
            p.stats(college)


        elif args.command == 'sync':
            p.text('Student tally spreadsheet sync ({} to {}).\n'.format(args.start, args.end))

            # Fetch student and config data
            if get_config(config, 'REPORT', 'shifts_year1') is None:
                shift_obligations = None
            else:
                shift_obligations = {
                    'Year1':    get_config(config, 'REPORT', 'shifts_year1'),
                    'Year2':    get_config(config, 'REPORT', 'shifts_year2'),
                    'Year3':    get_config(config, 'REPORT', 'shifts_year3'),
                    'Year1NR':  get_config(config, 'REPORT', 'shifts_year1_nr')}  
            location_name  = get_config(config, 'REPORT', 'location_name')

            # Google Sheet
            scopes = ['https://spreadsheets.google.com/feeds',
                     'https://www.googleapis.com/auth/drive']

            credentials = ServiceAccountCredentials.from_json_keyfile_name(service_account_credentials, scopes)
            gc = gspread.authorize(credentials)

            sheet = gc.open_by_key(google_sheet_id)

            result = sync_with_sheet(args.endpoint, args.token, args.timeout, sheet, 
                shift_obligations, location_name, include_list, args.start, args.end)

            for key in result.keys():
                print(key, result[key])


        elif args.command == 'api':
            # e.g. python3 deputy.py api --api resource/EmployeeRole
            p.text('Fetching api...{0}', args.api)
            api_resp = college.api(args.api)
            print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))
            print('{0} API records returned.'.format(len(api_resp)))


        elif args.command == 'resource':
            # e.g. python3 deputy.py resource --resource
            p.text('Fetching resource...{}', args.resource)
            api_resp = college.resource(args.resource)
            print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))
            print('{0} Resource records returned.'.format(len(api_resp)))


        elif args.command == 'rd':
            # e.g. python3 deputy.py resource --resource
            p.text('Fetching resource by Date...{}, ({} to {})', args.resource, args.start, args.end)
            api_resp = college.resource(args.resource, 
                select=[
                    ('Date', 'ge',  args.start),
                    ('Date', 'le',  args.end)
                ])
            print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))
            print('{0} Resource records returned.'.format(len(api_resp)))


        elif args.command == 'rc':
            # e.g. python3 deputy.py resource --resource
            p.text('Fetching resource by Created date...{}, ({} to {})', args.resource, args.start, args.end)
            api_resp = college.resource(args.resource, 
                select=[
                    ('Created', 'ge',  args.start),
                    ('Created', 'le',  args.end)
                ])
            print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))
            print('{0} Resource records returned.'.format(len(api_resp)))


        elif args.command == 'test':
            #pass
            
            #location_name = get_config(config, 'REPORT', 'location_name')
            #y = college.student_roster_count(location_name, start_date=args.start, end_date=args.end)
            
            #y = college.student_years()
            #y = college.employees(key='Id', join=['ContactObject'])

            # api_resp = college.student_years()
            # print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))
            # sys.exit(0)
            
            #print(json.dumps(list(y), sort_keys=True, indent=4, separators=(',', ': ')))
            #print('{0} records returned.'.format(len(y)))

            #for employee in self.employees(join=['ContactObject']):
            #    email_address = employee['ContactObject']['Email']

            #p.text('Fetching rosters...')
            #rosters = deputy.get_resources('Roster')
            #for r in rosters:
            #    # "StartTimeLocalized": "2016-03-16T13:30:00+11:00",
            #    # if r['StartTimeLocalized'].startswith('2016-04-14T09:30'):
            #    # 674 = Fred Smith
            #    #if r['Employee'] == 439:
            #    #    print(json.dumps(r, sort_keys=True, indent=4, separators=(',', ': ')))
            #    if r['Comment'] is not None:
            #        if len(r['Comment']) > 0:
            #            print(json.dumps(r, sort_keys=True, indent=4, separators=(',', ': ')))

            #api_resp = college.student_years()
            ##print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))
            #for r in api_resp:
            #    if r == 504:
            #        print(json.dumps(api_resp[r], sort_keys=True, indent=4, separators=(',', ': ')))
            #print(len(api_resp))

            ##DELETE /resource/:object/:id
            #api_resp = college.api('resource/TrainingRecord/321', method='DELETE')
            #print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))

            #api_resp = college.api('resource/Employee/845', method='POST', data={'Active': False})
            #print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))

            #students = college.discarded_employee_by_email()

            #api_resp = college.api('resource/Employee/845')
            #print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))

            #api_resp = college.api('resource/Employee/845', method='DELETE')
            #print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))

            #student_years = college.student_years()
            #print(json.dumps(student_years, sort_keys=True, indent=4, separators=(',', ': ')))

            # api_resp = college.resource('TrainingModule')
            # print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))


            # api_resp = college.api('resource/Contact/2313', method='POST', data={'Email1':'hughm@trinity.unimelb.edu.au'})
            # print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))

            # api_resp = college.api('resource/Contact/2148', method='POST', data={'Email1':'jakeh@trinity.unimelb.edu.au'})
            # print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))

            # ---
            # student = 897

            # start_date = args.start
            # end_date   = args.end
            # location_name  = get_config(config, 'REPORT', 'location_name')

            # ---
            # rosters = college.resource('Timesheet', join=['OperationalUnitObject'], 
            #     select=[
            #         ('Employee', 'ne',  0),
            #         ('Date', 'ge',  start_date),
            #         ('Date', 'le',  end_date)
            #     ])
            # students = Counter()
            # students.add_counter('rostered',  'Rosters Rostered')
            # students.add_counter('completed', 'Rosters Completed')
            # students.add_counter('open',      'Rosters Open')

            # count = 0
            # for id in rosters:
            #     roster = rosters[id]
            #     # ignore if there is no location or it's not a match
            #     if location_name is not None:
            #         if roster['OperationalUnitObject']['CompanyName'] != location_name:
            #             continue
            #     employee_id = roster['Employee']
            #     timesheet = roster['MatchedByTimesheet']
            #     students.count(employee_id, 'rostered')
            #     if timesheet > 0:
            #         students.count(employee_id, 'completed')
            #     if roster['Open']:
            #         students.count(employee_id, 'open')

            #     if employee_id == student:
            #         print(employee_id, students[student], 'timesheet=', timesheet, 'StartTimeLocalized', roster['StartTimeLocalized'])
            #         #print(json.dumps(roster, sort_keys=True, indent=4, separators=(',', ': ')), '\n\n')

            #         count += 1

            # print('count', count)

            # ---
            # timesheets = college.resource('Timesheet', join=['OperationalUnitObject'], 
            #     select=[
            #         ('Date', 'ge',  start_date),
            #         ('Date', 'le',  end_date)
            #     ])
            # students = Counter()
            # students.add_counter('timesheet', 'Timesheet')
            # for id in timesheets:
            #     timesheet = timesheets[id]
            #     # ignore if there is no location or it's not a match
            #     if location_name is not None:
            #         if timesheet['OperationalUnitObject']['CompanyName'] != location_name:
            #             continue
            #     # make sure someone approved then
            #     if not timesheet['TimeApproved']:
            #         continue
            #     # make sure they are not a leave timesheet
            #     if timesheet['IsLeave']:
            #         continue
            #     employee_id = timesheet['Employee']
            #     students.count(employee_id, 'timesheet')

            #     if employee_id == student:
            #         print(employee_id, students[student], 'EndTimeLocalized', timesheet['EndTimeLocalized'], 'TimeApproved', timesheet['TimeApproved'])
            #         #print(json.dumps(timesheet, sort_keys=True, indent=4, separators=(',', ': ')), '\n\n')


            # ---
            api_resp = college.api('resource/Timesheet/QUERY', method='POST')
            data = json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': '))

            print(data)
            print('\nLength of data', len(api_resp))


    except DeputyException as e:
        print(str(e))
        sys.exit(1)

    sys.exit(0)
