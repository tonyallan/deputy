# [Deputy](https://www.deputy.com/features)
Reporting and Utility script using the [deputy.com](https://www.deputy.com) [API](https://api-doc.deputy.com/API/Getting_Started).

## Introduction

This script is used by an educational institution where around 250 residental students are required to work in the kitchen on 'Bursary' shifts. The functionality is focussed on the need to manage and report on these students.

The `deputy.py` Python script contains examples on how to invoke the API's.

## Setup

### Minimal Configuration
You need a configuration file called `deputy.config` (in the current directory) that contains at least:

```
[DEPUTY]
api_endpoint  = https://xxx.au.deputy.com/api/v1/
access_token  = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```
The `api_endpoint` is your normal Deputy url with `/api/v1` appended.

To create your token, create a service account as a Systems Administrator, logon as that user, then get a Permanent Token using the instructions [here](http://api-doc.deputy.com/API/Authentication).

Copy the value to `access_token`.

### Configuration

`deptuty.config` shows all available configuration options.

## Commands

|Command|Purpose|Options|
|-------|-------|-------|
|`intro` (and default command)|Helpful documentation, i.e. directs users to this page!||
|`config`|List the contents of the configuration file (usually just a test to see if the config file can be read)||
|`list`|Show all users Name, Year and Email. Year will be blank if Training doesn't contain Year1, Year2 or Year3.|`--csv` output CSV to stdout|
|`report`|List users, showing all or some of 'Name', 'Year', 'Obligation', 'Rostered', 'Open', 'Completed', '% Rostered', '% Completed', 'Timesheets', 'Issues'|`--csv` output CSV to stdout; `--mobile` include a mobile phone number in the output CSV file.|
|`journal`|List all journal entries.|`--csv` output CSV to stdout|
|`deputy-csv`|Read from `import_csv` and write to `deputy.csv` (in the correct format to allow bulk People creation.||
|`add-year`|Extract the year level from `import_csv`||
|`view-api`|`GET` a resource API and display the JSON result. Limitted to 500 results.|`--api` execute an api. The default is `me`. |
|`test`|Will execute the last test code I used. NOT RECOMMENDED unless you are playing with code!||

## Examples

The following example assumes that the latest version is always fetched from GitHub.
```
curl -s -H "Cache-control: no-cache" https://raw.githubusercontent.com/tonyallan/deputy/master/deputy.py | python3 - list
```
The first line shows the version and account asscoaietd with the provided credentials (from the `me` API call).
```
DeputyVersion: 3.0.1 running as Service Account For API.
```

Other exaplmes.

```
curl -s -H "Cache-control: no-cache" https://raw.githubusercontent.com/tonyallan/deputy/master/deputy.py | python3 - view-api --api resource/Employee 
```


