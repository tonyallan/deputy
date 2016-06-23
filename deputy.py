#!/usr/bin/env python3

# Copyright (c) 2016 Tony Allan

# This script is all a bit of a hack.
# Some effort has been made to put communication with the Deputy api into the Deputy class.

# The script can be used to:
# - convert the CSV file from Synergetic to a Duputy CSV useful for importing employee's into Deputy.
# - add a year level for each student using the training module employee field to conveniently store the data.

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
        print('[Fetching {0}={1} {2}]'.format(ptype, function, position))

    def api(self, api, method='GET', data=None, dp_meta=False):
        """
        At least for Resource calls, api_resp is a list of results.

        The dp-meta-option header is passed if dp_meta is set. This adds additional resonse data.

        Returns the API data.
        """
        #self.progress('api', api, 0)
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
            api_resp = json.loads(resp.read().decode('utf-8'))
        except ValueError:
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

    def stats(self, deputy):
        self.text('')
        for stat in deputy.stats:
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
        self.stats = None
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

        employees = self.employee_by_email()

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
            employee_id = employee['Id']

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
               'TrainingDate': datetime.datetime.now().isoformat(),
               'Active': True
            }
            api_resp = self.api('resource/TrainingRecord', method='POST', data=data)
            added_count += 1

        self.stats = None
        messages.append('Processed {0} students.'.format(count))
        messages.append('{0} students not found in Deputy.'.format(not_found_count))
        messages.append('{0} students already had a year level set.'.format(already_count))
        messages.append('Added year level to {0} students.'.format(added_count))
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
        api_resp = self.api('resource/TrainingModule')
        years = {}
        for tm in api_resp:
            if tm['Title'].startswith('Year'):
                years[tm['Title']] = tm['Id']
        self.stats = [self.Stat('years', 'Years', len(years))]
        return years

    def student_years(self):
        """
        This is a college specific method.
        Return a hash of year levels for each student (EmployeeId) who has a year assigned:
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
        self.stats = [self.Stat('training_records', 'Training Records', len(training_records))]
        return training_records

    def bursary_student_list(self):
        """
        List of Bursary Students.
        A Bursary Student is an employee who has a training record that includes Year1/2/3.
        """
        students = self.employees(join=['ContactObject'])
        student_years = self.student_years()
        Student = collections.namedtuple('Student', ['Id', 'Name', 'Year', 'Email'])
        result = []
        for student_id in students:
            student = students[student_id]
            name = student['DisplayName']
            if student_id in student_years:
                year = student_years[student_id]
            else:
                continue
            email_address = student['ContactObject']['Email']
            if year is not None:
                result.append(Student(student_id, name, year, email_address))
        self.stats = [
            self.Stat('students', 'Students', len(students)),
            self.Stat('bursary_students', 'Bursary Students', len(result))
            ]
        return result

    def deputy_journal_entries(self):
        """
        List of Journal Entries for activie employee's.
        """
        employees = self.employees(join=['ContactObject'])
        journals = self.resource('Journal')
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
        self.stats = [self.Stat('journal_entries', 'Journal Entries', len(result))]
        return result

    def student_timesheet_count(self, location_name):
        """
        Return a count of approved, non-leave timesheets by employee_id.
        """
        timesheets = self.resource('Timesheet', join=['OperationalUnitObject'])
        students = Counter()
        students.add_counter('timesheet', 'Timesheet')
        for id in timesheets:
            timesheet = timesheets[id]
            # ignore if there is no location or it's not a match
            if location_name is not None:
                if timesheet['OperationalUnitObject']['CompanyName'] != location_name:
                    continue
            # make sure someone approved then
            if not timesheet['TimeApproved']:
                continue
            # make sure they are not a leave timesheet
            if timesheet['IsLeave']:
                continue
            employee_id = timesheet['Employee']
            students.count(employee_id, 'timesheet')
        return students

    def student_roster_count(self, location_name):
        """
        Return a count of approved, non-leave timesheets by Employee for the selected location.
        Employee may be for an inactive employee.
        Employee is ignored if it is zero.
        """
        rosters = self.resource('Roster', join=['OperationalUnitObject'], select=[('Employee', 'ne',  0)])
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
        self.stats = [
            self.Stat('rosters',   'Rosters (for all locations)',   len(rosters)),
            self.Stat('students',  'Rosters with Students',  len(students))
        ]
        for total in students.get_totals():
            self.stats.append(self.Stat(*total))
        return students

    def student_report(self, obligation_by_year, location_name):
        """
        Student roster data.
        Timesheet data exists but is not currently used.
        """
 
        # fetch student.Id, student.Name, and student.Year
        students = self.bursary_student_list()

        # count approved, non-leave 'timesheet'
        #student_timesheet_count = self.student_timesheet_count(location_name)

        # count 'rostered', 'completed', 'open' rosters
        student_roster_count = self.student_roster_count(location_name)
        roster_stats = self.stats
        #print(json.dumps(roster_stats, indent=4, separators=(',', ': ')))
        
        Report = collections.namedtuple('Report', ['Name', 'Year', 'Obligation', 'Rostered', 'Open', 'Completed', 
                'PercentRostered', 'PercentCompleted', 'Issues']) # removed 'Timesheets'

        counts = Counter()
        counts.add_counter('Year1',                  'Students in Year 1')
        counts.add_counter('Year2',                  'Students in Year 2')
        counts.add_counter('Year3',                  'Students in Year 3')
        counts.add_counter('roster_rostered_count',  'Rostered')
        counts.add_counter('roster_completed_count', 'Completed Rosters')
        counts.add_counter('roster_open_count',      'Open Rosters')

        # write out the sorted list of results with a percentage complete
        # loop using student_list because it is sorted and therefore the report will be sorted.
        result = []
        for student in students:
            # student.Id, student.Name, student.Year
            #if student.Id in student_timesheet_count:
            #    stc = student_timesheet_count[student.Id]
            #else:
            #    stc = {'timesheet': 0}
            if student.Id in student_roster_count:
                src = student_roster_count[student.Id]
            else:
                src = {'rostered': 0, 'completed': 0, 'open': 0}
            counts.count(id='roster_rostered_count',  increment=src['rostered'])
            counts.count(id='roster_completed_count', increment=src['completed'])
            counts.count(id='roster_open_count',      increment=src['open'])
            obligation = int(obligation_by_year[student.Year])
            counts.count(id=student.Year)
            issues = ''

            percentage_rostered = '{0:.0f}%'.format(((0.0+src['rostered'])/obligation)*100.0)
            if (0.0+src['rostered'])/obligation < 1:
                issues = 'Incomplete roster. '
            percentage_complete = '{0:.0f}%'.format(((0.0+src['completed'])/obligation)*100.0)
            if (0.0+src['completed'])/obligation < 1:
                issues += 'Outstanding Shifts.'

            result.append(Report(student.Name, student.Year, obligation, 
                src['rostered'], src['open'], src['completed'], percentage_rostered, 
                percentage_complete, issues)) # removed stc['timesheet']

        # and some summary info
        self.stats = []
        self.stats.append(self.Stat('student_bursary', 'Bursary Students', len(students)))
        #self.stats.append(self.Stat('student_timesheet', 'Students with Timesheets', len(student_timesheet_count)))
        self.stats.append(self.Stat('student_roster', 'Students with Rosters', len(student_roster_count)))
        for total in counts.get_totals():
            self.stats.append(self.Stat(*total))
        return result


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

    import_csv     = get_config(config, 'IMPORT', 'import_csv', missing='import.csv')
    deputy_csv     = get_config(config, 'IMPORT', 'deputy_csv', missing='deputy.csv')
    email_test     = get_config(config, 'IMPORT', 'email_test')
    email_domain   = get_config(config, 'IMPORT', 'email_domain')

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
    parser = argparse.ArgumentParser(description='Deputy Reporting and Utilities')
    parser.add_argument('-e', '--endpoint', help='API endpoint (override config file)',
        default=get_config(config, 'DEPUTY', 'api_endpoint'))
    parser.add_argument('-a', '--token',    help='Access Token (override config file)',
        default=get_config(config, 'DEPUTY', 'access_token'))
    parser.add_argument('--import_csv',     help='Import CSV (override config file)',
        default=import_csv)
    parser.add_argument('--deputy_csv',     help='Deputy CSV output (override config file)',
        default=deputy_csv)
    parser.add_argument('-t', '--timeout',  help='HTTP timeout',
        default=20, type=int)
    parser.add_argument('command',          help='command (e.g. status)',
        default='intro', nargs='?',
        choices=['intro', 'config', 'list', 'report', 'journal', 'user-csv', 'add-year', 'api', 'resource', 'test'])
    parser.add_argument('--api',            help='View API',
        default='me')
    parser.add_argument('--resource',       help='View Response',
        default='Employee')
    parser.add_argument('--mobile',         help='Include Mobile phone number in the Deputy CSV file', action='store_true')
    parser.add_argument('--csv',            help='Format output as CSV',  action='store_true')
    parser.add_argument('--hide_ok',        help='In report, hide if no problems.', action='store_true')
    args = parser.parse_args()

    # All exceptions are fatal. API errors are displayed in the except statement.
    try:
        p = Printx(csv_flag=args.csv)
        #deputy = Deputy(args.endpoint, args.token, args.timeout)
        college = College(args.endpoint, args.token, args.timeout)
        api_resp = college.api('me')        

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
            writer = csv.DictWriter(out_csv, fieldnames=college.DEPUTY_COLS)
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
            years = college.years()
            p.text('Fetching training records (for year)...')
            student_years = college.student_years()
            messages = college.add_years_to_student_records(years, student_years, import_csv)
            p.text('\n'.join(messages))

        elif args.command == 'list':
            p.text('List of Bursary Students and their year level and email.\n')
            p.headers('Id', 'Name', 'Year', 'Email')
            for s in college.bursary_student_list():
                p.data('[{0}] {1} ({2}, {3})', s.Id, s.Name, s.Year, s.Email)
            p.stats(college)

        elif args.command == 'journal':
            p.text('Journal Entries.\n')
            p.headers('Date', 'Name', 'Email', 'Category', 'Comment', 'Creator')
            for e in college.deputy_journal_entries():
                p.data('[{0}] {1} ({2}) [{3}] {4} (by {5})', e.Date, e.Name, e.Email, e.Category, e.Comment, e.Creator)
            p.stats(college)

        elif args.command == 'report':
            p.text('Student compliance report.\n')

            p.headers('Name', 'Year', 'Obligation', 'Rostered', 'Open', 'Completed', 
                '% Rostered', '% Completed', 'Issues') # removed for now 'Timesheets'

            # Fetch student and config data
            if get_config(config, 'REPORT', 'shifts_year1') is None:
                shift_obligations = None
            else:
                shift_obligations = {
                    'Year1': get_config(config, 'REPORT', 'shifts_year1'),
                    'Year2': get_config(config, 'REPORT', 'shifts_year2'),
                    'Year3': get_config(config, 'REPORT', 'shifts_year3')}  
            location_name  = get_config(config, 'REPORT', 'location_name')
            for student in college.student_report(shift_obligations, location_name):
                p.data('{0} ({1}): {2}, {3}, {4} {5} {6} {7} {8}', *student)
            p.stats(college)

        elif args.command == 'api':
            # e.g. python3 deputy.py api --api resource/EmployeeRole
            p.text('Fetching api...{0}', args.api)
            api_resp = college.api(args.api)
            print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))
            print('{0} API records returned.'.format(len(api_resp)))

        elif args.command == 'resource':
            # e.g. python3 deputy.py resource --resource
            p.text('Fetching resource...{0}', args.resource)
            api_resp = college.resource(args.resource)
            print(json.dumps(api_resp, sort_keys=True, indent=4, separators=(',', ': ')))
            print('{0} Resource records returned.'.format(len(api_resp)))

        elif args.command == 'test':
            #pass
            location_name = get_config(config, 'REPORT', 'location_name')
            y = college.student_roster_count(location_name)
            #y = college.student_years()
            #y = college.employees(key='Id', join=['ContactObject'])
            print(json.dumps(y, sort_keys=True, indent=4, separators=(',', ': ')))
            print('{0} records returned.'.format(len(y)))

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


    except DeputyException as e:
        print(str(e))
        sys.exit(1)

    sys.exit(0)
