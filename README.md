# deputy
Reporting and Utility script using the deputy.com API

## Setup

You need a configuration file called `deputy.config` that contains at least:

```
[DEPUTY]
api_endpoint  = https://xxx.au.deputy.com/api/v1/
access_token  = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```
The `api_endpoint` is your normal Deputy url with `/api/v1` appended.

To create your token, create a service account as a Systems Administrator and then get a Permanent Token using the instructions [here](http://api-doc.deputy.com/API/Authentication).

Copy the value to `access_token`.
