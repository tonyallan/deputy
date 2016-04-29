# [Deputy](https://www.deputy.com/features)
Reporting and Utility script using the [deputy.com](https://www.deputy.com) [API](https://api-doc.deputy.com/API/Getting_Started).

## Introduction

This script is used by an educational institution where around 250 residental students are required to work in the kitchen on 'Bursary' shifts. The functionality is focussed on the need to manage and report on these students.

The `deputy.py` Python script contains examples on how to invoke the API's.

## Setup

You need a configuration file called `deputy.config` (in the current directory) that contains at least:

```
[DEPUTY]
api_endpoint  = https://xxx.au.deputy.com/api/v1/
access_token  = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```
The `api_endpoint` is your normal Deputy url with `/api/v1` appended.

To create your token, create a service account as a Systems Administrator, logon as that user, then get a Permanent Token using the instructions [here](http://api-doc.deputy.com/API/Authentication).

Copy the value to `access_token`.
