
import os
import json
import os.path
import requests
import pandas as pd
from bs4 import BeautifulSoup
import xmltodict
from time import sleep
from datetime import datetime, timedelta  # Added timedelta import
import boto3
from botocore.exceptions import NoCredentialsError
import subprocess
import prefect
from prefect import task, Flow, Parameter
from prefect.run_configs import KubernetesRun
import pyodbc
import logging
import pendulum
from prefect.utilities.logging import get_logger
from requests.adapters import HTTPAdapter, Retry
from snowflake.connector.cursor import SnowflakeCursor
from pgr_snowflake.connect import connect_service_via_oauth
import smtplib
from prefect.schedules import CronSchedule

# Define the logger
log = get_logger()
log.setLevel("DEBUG")

# Test file name to make sure s3 works in prefect
PREFECT_AGENT_ENV = os.environ.get('PREFECT_AGENT_ENV')
project_name = os.environ.get('project_name')

previous_day = datetime.now() - timedelta(days=1)  # Using timedelta
date = previous_day.strftime('%Y%m%d')

fname = f'seoclarity_out_{date}.log'
keyword_list = []
se_list = ["bing", "google"]

if (PREFECT_AGENT_ENV == "Prod" or (project_name and any(item in project_name for item in ['-prod', '-gold']))):
    env_letter = "P"
    env_abbr = "prod"
    smtp_server = "smtp.3d.prci.com"
    job_email_distro_success = ['samuel_benya@progressive.com', 'jacob_t_patterson@progressive.com','Abhiram_Pamidi@progressive.com']
    job_email_distro_failure = ['samuel_benya@progressive.com', 'jacob_t_patterson@progressive.com','Abhiram_Pamidi@progressive.com']
    schedule = CronSchedule("0 14 * * *", start_date=pendulum.now("America/New_York"))
    schedule.next(7)
else:
    env_letter = "D"
    env_abbr = "dev"
    smtp_server = "testsmtp.3d.prci.com"
    job_email_distro_success = ['samuel_benya@progressive.com','Abhiram_Pamidi@progressive.com']
    job_email_distro_failure = ['samuel_benya@progressive.com','Abhiram_Pamidi@progressive.com']
    schedule = None

snowflake_account = 'progressive.us-east-1'

# Dictionary to store keyword counts and offsets
keyword_stats = {
    'google_d': {'count': 0, 'first_offset': None, 'last_offset': None},
    'google_m': {'count': 0, 'first_offset': None, 'last_offset': None},
    'bing_d': {'count': 0, 'first_offset': None, 'last_offset': None},
    'bing_m': {'count': 0, 'first_offset': None, 'last_offset': None}
}

def send_email_alert_on_failure(flow, old_state, new_state):
    if new_state.is_failed():
        if isinstance(new_state.result, Exception):
            value = "```{}```".format(repr(new_state.result))
        else:
            value = new_state.message
        flow_name_ = prefect.context.flow_name
        run_name_ = prefect.context.flow_run_name
        id_ = prefect.context.flow_run_id
        logger = prefect.context.get("logger")
        logger.info("Trying to send failure email now")
        sender = 'no-reply@Progressive.com'
        receivers = job_email_distro_failure
        failure_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        SUBJECT = f"Quoting DE Job: SEO Clarity Daily Get- Failure on flow: \"{flow_name_}\""
        TEXT = (
            f"We have a failure on flow: \"{flow_name_}\" called: \"{run_name_}\". "
            f"It has run id: \"{id_}\".\n\n"
            f"Failure Time: {failure_time}\n"
            f"Error: {value}\n"
            f"Keywords Collected: {len(keyword_list)}\n"
            f"Date of Keyword Search: {date}\n\n"
            f"Here is a link to the flow's log: https://cloud.prefect.io/pgr-quotingde/flow-run/{id_}?logs.\n\n"
            f"Please contact samuel_benya@progressive.com"
        )
        message = 'Subject: {}\n\n{}'.format(SUBJECT, TEXT)
        smtpObj = smtplib.SMTP(smtp_server)
        smtpObj.sendmail(sender, receivers, message)         
        logger.info("failure email sent")
    return new_state

def xml_to_dict(response):
    data_dict = xmltodict.parse(response.content)
    json_data = json.dumps(data_dict)
    b = json.loads(json_data)
    return b

def f_out(json_data, f):
    with open(f, "a") as f:
        f.write(json.dumps(json_data) + "\n")

def se_call(device, logger):
    for se in se_list:
        logger.info(f"Starting keyword collection for search engine: {se} and device: {device}")
        offset = 0  # Reset offset for each search engine
        total_keywords_collected = 0  # Initialize counter for keywords collected for this permutation
        first_offset = None
        last_offset = None
        while True:
            try:
                keywords_collected, current_offset = keyword_call(offset, se, device, logger)  # either dict or Nonetype
                if first_offset is None:
                    first_offset = current_offset
                last_offset = current_offset
                if keywords_collected is None:
                    logger.info('End of keywords')
                    logger.info(f"Last offset: {offset}")
                    break
                total_keywords_collected += keywords_collected
                offset += 100
                sleep(1)
            except Exception as e:
                logger.error(f"Error occurred while processing {se} on device {device} with offset {offset}: {e}")
                break  # or continue, depending on how you want to handle errors
        logger.info(f"End of keyword collection for search engine: {se} and device: {device}")
        logger.info(f"Total keywords collected for {se} on {device}: {total_keywords_collected}")

        # Update keyword_stats dictionary
        key = f"{se}_{device}"
        keyword_stats[key]['count'] = total_keywords_collected
        keyword_stats[key]['first_offset'] = first_offset
        keyword_stats[key]['last_offset'] = last_offset
    return

def keyword_call(offset, se, device, logger):
    API_KEY = os.environ['SEO_APIKEY_1']
    s = requests.Session()
    retries = Retry(total=50, backoff_factor=1, status_forcelist=[502, 503, 504])
    s.mount('http://', HTTPAdapter(max_retries=retries))
    url = 'http://api.seoclarity.net/seoClarity/keyword?'
    params = {
        'access_token': os.environ['SEO_APIKEY_1'],
        'offset': offset,
        'Limit': '100',  # this applies to everything in the call. dates, etc.
        'sDate': date,
        'eDate': date,
        'engine': se,
        'device': device,
        'market': 'en-us',
    }
    try:
        resp = s.get(url=url, params=params)
        # Check for HTTP 500 errors and raise an exception if found
        if resp.status_code == 500:
            raise Exception(f"HTTP 500 error encountered for {se} on device {device} with offset {offset}")
        kw_dict = xml_to_dict(resp)
        try:
            if kw_dict['keywords'] is not None:
                num_keywords = len(kw_dict['keywords']['keyword'])
                logger.info(f"Number of keywords returned for {se} on {device} with offset {offset}: {num_keywords}")
                for i in kw_dict['keywords']['keyword']:
                    i.setdefault('device', device)
                    i.setdefault('engine', se)
                    keyword_list.append(i)
                    f_out(i, fname)
                return num_keywords, offset
            else:
                logger.info('Empty list')
                return None, offset
        except IndexError as e:
            logger.info(f"Got {e}")
        return True, offset

    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTP error occurred: {http_err}")
        raise
    except requests.exceptions.ConnectionError as conn_err:
        logger.error(f"Connection error occurred: {conn_err}")
        raise
    except requests.exceptions.Timeout as timeout_err:
        logger.error(f"Timeout error occurred: {timeout_err}")
        raise
    except requests.exceptions.RequestException as req_err:
        logger.error(f"An error occurred: {req_err}")
        raise

@task
def device_call_task():
    devices = ['d', 'm']
    logger = prefect.context.get("logger")
    for device in devices:
        logger.info("getting device: " + device)
        try:
            se_call(device, logger)  # Pass the logger argument here
        except Exception as e:
            logger.error(f"Error occurred while processing device {device}: {e}")
    return len(keyword_list)

# Conditional task to check the number of collected keywords
@task
def check_keyword_count(keyword_count, min_keywords_threshold):
    if keyword_count < min_keywords_threshold:
        raise ValueError(f"Insufficient keywords collected: {keyword_count}. Minimum required is {min_keywords_threshold}.")
    return True

@task
def upload_to_s3_task(fname):
    p = subprocess.Popen(['pgraws', '-c', '-r', 'D-U-AWS35D-QUOTING-CORE'])
    p.wait()
    logger = prefect.context.get("logger")
    logger.info("uploading file")
    logger.info(fname)
    bucket = 'pgr-quoting-core-dev-aws35d-data'
    local_file = fname
    s3_key = 'seo_clarity/logs/' + fname
    s3 = boto3.client('s3')
    try:
        s3.upload_file(local_file, bucket, s3_key)
        logger.info(f"{local_file} uploaded to {bucket} as {s3_key}")
    except FileNotFoundError:
        logger.info(f"The file {local_file} was not found")
    except NoCredentialsError:
        logger.info("Credentials not available")

@task
def success_email_task():
    logger = prefect.context.get("logger")
    logger.info("Trying to send success email now")

    # Get the number of rows collected
    num_rows_collected = len(keyword_list)

    # Get the current time when the email is being sent
    run_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Count rows for each combination of search engine and device
    google_mobile_count = sum(1 for kw in keyword_list if kw.get('engine') == 'google' and kw.get('device') == 'm')
    google_desktop_count = sum(1 for kw in keyword_list if kw.get('engine') == 'google' and kw.get('device') == 'd')
    bing_mobile_count = sum(1 for kw in keyword_list if kw.get('engine') == 'bing' and kw.get('device') == 'm')
    bing_desktop_count = sum(1 for kw in keyword_list if kw.get('engine') == 'bing' and kw.get('device') == 'd')

    sender = 'no-reply@Progressive.com'
    receivers = job_email_distro_success
    SUBJECT = "Quoting DE Job: SEO Clarity Daily Get ran successfully!"
    TEXT = (
        f"Hello! The {env_abbr.upper()} workflow for SEO Clarity Daily Get has succeeded and {fname} "
        f"has been uploaded to pgr-quoting-core-dev-aws35d-data/seo_clarity/logs/{fname}.\n\n"
        f"Details:\n"
        f"Date Collected: {date}\n"
        f"Number of Rows Collected: {num_rows_collected}\n"
        f"Run Time: {run_time}\n\n"
        f"Counts by Search Engine and Device:\n"
        f"Google Mobile: {google_mobile_count}\n"
        f"Google Desktop: {google_desktop_count}\n"
        f"Bing Mobile: {bing_mobile_count}\n"
        f"Bing Desktop: {bing_desktop_count}\n\n"
    )
    message = 'Subject: {}\n\n{}'.format(SUBJECT, TEXT)
    smtpObj = smtplib.SMTP(smtp_server)
    smtpObj.sendmail(sender, receivers, message)         
    logger.info("success email sent")

with Flow("seo-call-daily-09", schedule=schedule, state_handlers=[send_email_alert_on_failure]) as flow:
    device_call = device_call_task(task_args=dict(name="device_call"))

    keyword_count_check = check_keyword_count(device_call, 40000)

    upload_to_s3 = upload_to_s3_task(fname, task_args=dict(name="upload_to_s3"), upstream_tasks=[keyword_count_check])
    success_email = success_email_task(task_args=dict(name="success_email"), upstream_tasks=[upload_to_s3])

if __name__ == "__main__":
    flow.run()
