#!/usr/bin/env python
# -*- coding: utf-8 -*-

import datetime
import json
from os.path import exists

import boto3
from pkg_resources import resource_filename

# Use AWS Pricing API through Boto3. API only has us-east-1 and ap-south-1 as valid endpoints.
# It doesn't have any impact on your selected region for your instance.
client_pricing = boto3.client('pricing', region_name='us-east-1')

# Search product filter. This will reduce the amount of data returned by the
# get_products function of the Pricing API
FLT = '[{{"Field": "tenancy", "Value": "shared", "Type": "TERM_MATCH"}},' \
      '{{"Field": "operatingSystem", "Value": "{o}", "Type": "TERM_MATCH"}},' \
      '{{"Field": "preInstalledSw", "Value": "NA", "Type": "TERM_MATCH"}},' \
      '{{"Field": "instanceType", "Value": "{t}", "Type": "TERM_MATCH"}},' \
      '{{"Field": "location", "Value": "{r}", "Type": "TERM_MATCH"}},' \
      '{{"Field": "capacitystatus", "Value": "Used", "Type": "TERM_MATCH"}}]'

PRICING_FILE_NAME = 'aws_pricing.json'
PRICING_MAX_AGE = datetime.timedelta(hours=24)


def get_price(region, instance, os):
    """
    Get current AWS price for an on-demand instance.
    """
    f = FLT.format(r=region, t=instance, o=os)
    data = client_pricing.get_products(ServiceCode='AmazonEC2', Filters=json.loads(f))
    price = None
    if data['PriceList']:
        od = json.loads(data['PriceList'][0])['terms']['OnDemand']
        id1 = list(od)[0]
        id2 = list(od[id1]['priceDimensions'])[0]
        price = od[id1]['priceDimensions'][id2]['pricePerUnit']['USD']
    return price


def get_region_name(region_code):
    """
    Translate region code to region name. Even though the API data contains
    regionCode field, it will not return accurate data. However, using the location
    field will, but then we need to translate the region code into a region name.
    You could skip this by using the region names in your code directly, but most
    other APIs are using the region code.
    """
    default_region = 'US East (N. Virginia)'
    endpoint_file = resource_filename('botocore', 'data/endpoints.json')
    try:
        with open(endpoint_file, 'r') as f:
            data = json.load(f)
        # Botocore is using Europe while Pricing API using EU...sigh...
        return data['partitions'][0]['regions'][region_code]['description'].replace('Europe', 'EU')
    except IOError:
        return default_region


def load_from_file():
    """
    Load prices from file
    """
    prices = None
    if exists(PRICING_FILE_NAME):
        print('Loading pricing from file ...')
        with open(PRICING_FILE_NAME, 'r') as f:
            prices = json.load(f, object_hook=as_float)
        price_list_date = datetime.datetime.strptime(prices['price_list_date'], '%Y-%m-%d %H:%M:%S')
        # If the pricing file is older than desired, then we need to get the new prices
        if datetime.datetime.now() - price_list_date > PRICING_MAX_AGE:
            print('Pricing file has expired ...')
            prices = None
    return prices


def as_float(obj):
    if 'cost_per_hour' in obj and obj['cost_per_hour']:
        obj['cost_per_hour'] = float(obj['cost_per_hour'])
    return obj


def get_pricing_from_api(instance_types: list):
    """
    Get current prices from AWS Pricing API
    """
    print('Requesting current pricing from AWS pricing API ...')
    # aws_batch_env = BasecallerBatch()
    regions = ['us-west-2', 'us-east-1', 'eu-central-1', 'eu-west-1', 'eu-west-2', 'me-south-1']
    operating_system = 'Linux'
    prices = {
        'price_list_date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'currency': 'USD',
        'instances': {},
    }
    for region in regions:
        prices['instances'][region] = {
            instance: {'cost_per_hour': get_price(get_region_name(region), instance, operating_system)}
            for instance in instance_types
        }
    with open(PRICING_FILE_NAME, 'w') as f:
        json.dump(prices, f, indent=4)
    prices = load_from_file()
    return prices


def get_pricing(instance_types: list):
    """
    Get current prices
    """
    prices = load_from_file()
    if not prices:
        prices = get_pricing_from_api(instance_types)
    return prices
