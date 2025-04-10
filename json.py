import requests
import time
import logging
from datetime import datetime, timedelta
from urllib.request import urlretrieve

# Configuration
se_list=["google.com"]
devices=['mobile']
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def generate_dates_for_month(year: int, month: int) -> list:
    """
    Generate a list of dates for a given month and year in the format YYYYMMDD.

    Args:
        year (int): The year for which to generate dates.
        month (int): The month for which to generate dates.

    Returns:
        list: A list of dates in the format YYYYMMDD.
    """
    dates = []
    start_date = datetime(year, month, 14)
    while start_date.month == month:
        dates.append(start_date.strftime("%Y%m%d"))
        start_date += timedelta(days=1)
    return dates

#dates=generate_dates_for_month(2025,1)
dates = ["20250305"]

def ranking_call() -> None:

    url = "https://api.seoclarity.net/seoClarity/task/v1/dailyRanking/ranking"
    headers = { "access_token":"9db9981b-9715-40cf-955a-501b9879cd8b","Cache-Control": "no-cache","Content-Type": "application/json"}
    for date in dates:
        for device in devices:
                for se_lis in se_list:
                        data = {
                        "device": device,
                        "top": 100,
                        "startDate": date,
                        "endDate": date,
                        "searchEngine": se_lis,
                        "language": "en",
                        "storageId": 0,
                        "locationId": 0,
                        "query": {
                            "filters": [
                            ]
                        }
                    }
                        s = requests.Session()
                        #retries = Retry(total=20, backoff_factor=1, status_forcelist=[502, 503, 504])
                        #s.mount('https://', HTTPAdapter(max_retries=retries))
                        print('getting data for '+date+' '+device+' '+se_lis)
                        response = s.post(url, headers=headers, json=data)
                        print(response.json())
                        file_hit(headers,  response.json()['taskId'])
    return

def file_hit(headers,taskid):
    urlrank='https://api.seoclarity.net/seoClarity/task/v1/dailyRanking/ranking/'+taskid
    status = True
    while status:
        sess=requests.Session();
        keywordresp=sess.get(urlrank,headers=headers)
        if (keywordresp.status_code != 200):
                    #check the the status and assign to offense_response.status_code
            print("Status code is not 200, entering sleep for 5 seconds")
            time.sleep(50)
        else:
            print("status code is 200, hence exiting")
            status = False
    files=keywordresp.json()['files']
    print(str(len(files)))
    for file in files:
          file_Path = file[61:61+73] +'.json'
          download_file_simple(file,file_Path)    
    return

def download_file_simple(url, filename):
    try:
        urlretrieve(url, filename)
        print(f"Successfully downloaded {filename}")
    except Exception as e:
        print(f"An error occurred: {e}")

def f_out(json_data: any, filename: str) -> None:
    """
    Append JSON data to a file.

    Args:
        json_data (Any): The data to be written to the file.
        filename (str): The name of the file to append the data to.
    """
    with open(filename, "wb") as f:
        f.write(json_data)

ranking_call()
#headers = { "access_token":"9db9981b-9715-40cf-955a-501b9879cd8b","Cache-Control": "no-cache","Content-Type": "application/json"}
#file_hit(headers=headers,device='desktop',se_lis='bing.com',taskid='task_id_37430909540ead4b209979b36c9da733_20250316024307')
