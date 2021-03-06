#!/bin/env python

""" 
The MIT License Copyright (c) 2010 The Chicago Tribune & Contributors Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation 
files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the 
Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions: The above copyright notice and this permission notice shall be included in all copies 
or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS 
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR 
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE. 
""" 

from multiprocessing import Pool 
import os 
import re 
import socket 
import time 
import urllib2 
import csv 
import math 
import random 
import boto 
import boto.ec2 
import paramiko 
import subprocess

STATE_FILENAME = os.path.expanduser('~/.bees')

# Utilities
def _read_server_list():
    instance_ids = []
    if not os.path.isfile(STATE_FILENAME):
        return (None, None, None, None)
    with open(STATE_FILENAME, 'r') as f:
        username = f.readline().strip()
        key_name = f.readline().strip()
        zone = f.readline().strip()
        text = f.read()
        instance_ids = text.split('\n')
        print 'Read %i bees from the roster.' % len(instance_ids)
    return (username, key_name, zone, instance_ids) 

def _write_server_list(username, key_name, zone, instances):
    with open(STATE_FILENAME, 'w') as f:
        f.write('%s\n' % username)
        f.write('%s\n' % key_name)
        f.write('%s\n' % zone)
        f.write('\n'.join([instance.id for instance in instances])) 

def _delete_server_list():
    os.remove(STATE_FILENAME) 

def _get_pem_path(key):
    print "Getting pem path for key %s" % key
    pem_path = os.path.expanduser('~/.ssh/%s.pem' % key)
    print "Obtained full key path: %s" % pem_path
    return pem_path

def _get_region(zone):
    return zone[:-1] # chop off the "d" in the "us-east-1d" to get the "Region"
	
def _get_security_group_ids(connection, security_group_names, subnet):
    ids = []
    # Since we cannot get security groups in a vpc by name, we get all security groups and parse them by name later
    security_groups = connection.get_all_security_groups()
	
    # Parse the name of each security group and add the id of any match to the group list
    for group in security_groups:
        for name in security_group_names:
            if group.name == name:
                if subnet == None:
                    if group.vpc_id == None:
                        ids.append(group.id)
                    elif group.vpc_id != None:
                        ids.append(group.id)
		
        return ids 

def _upload_to_instance(source, params, scp_options):
    print "Attempting to upload file %s to instance %i." % (source, params['i'])
    try:
        pem_file_path=_get_pem_path(params['key_name'])
        scp_command = "scp -q -o %s'StrictHostKeyChecking=no' -i %s %s %s@%s:/tmp/honeycomb" % (scp_options, pem_file_path, source, params['username'], params['instance_name'])
        #print "Running SCP command: %s" % scp_command
        scp_out = os.system(scp_command)
        if scp_out > 0:
            print "Unable to upload file to instance, scp exited with error code: %i" % scp_out
        else:
            print "File uploaded to instance %i successfully." % params['i'] 
    except e:
        print "Exception occurred while uploading file to instance %i. Details: %s" % (params['i'], e)
        return e

def _download_from_instance(source, destination, params, scp_options):
    print "Attempting to download file %s from instance %i." % (source, params['i'])
    try:
    	pem_file_path=_get_pem_path(params['key_name'])
    	scp_command = "scp -q -o %s 'StrictHostKeyChecking=no' -i %s %s@%s:%s %s" % (scp_options, pem_file_path, params['username'], params['instance_name'], source, destination)
        #print "Running SCP command: %s" % scp_command
        scp_out = os.system(scp_command)
        if scp_out > 0:
            print "Unable to download file from instance, scp exited with error code: %i" % scp_out
        else:
            print "File downloaded from instance %i successfully." % params['i']
    except e:
        print "Exception occurred while downloading file from instance %i. Details: %s" % (params['i'], e)
        return e

# Methods

def up(count, group, zone, image_id, instance_type, username, key_name, subnet):
    """
    Startup the load testing server.
    """
    existing_username, existing_key_name, existing_zone, instance_ids = _read_server_list()
    if instance_ids:
        print 'Bees are already assembled and awaiting orders.'
        return
    count = int(count)
    pem_path = _get_pem_path(key_name)
    if not os.path.isfile(pem_path):
        print 'No key file found at %s' % pem_path
        return
    print 'Connecting to the hive.'
    ec2_connection = boto.ec2.connect_to_region(_get_region(zone))
    print 'Attempting to call up %i bees.' % count
    reservation = ec2_connection.run_instances(
        image_id=image_id,
        min_count=count,
        max_count=count,
        key_name=key_name,
        security_group_ids=_get_security_group_ids(ec2_connection, [group], subnet),
        instance_type=instance_type,
        placement=zone,
        subnet_id=subnet)
    print 'Waiting for bees to load their machine guns...'
    instance_ids = []
    for instance in reservation.instances:
        instance.update()
        while instance.state != 'running':
            print '.'
            time.sleep(5)
            instance.update()
        instance_ids.append(instance.id)
        print 'Bee %s is ready for the attack.' % instance.id
    ec2_connection.create_tags(instance_ids, { "Name": "a bee!" })
    _write_server_list(username, key_name, zone, reservation.instances)
    print 'The swarm has assembled %i bees.' % len(reservation.instances) 

def report():
    """
    Report the status of the load testing servers.
    """
    username, key_name, zone, instance_ids = _read_server_list()
    if not instance_ids:
        print 'No bees have been mobilized.'
        return
    ec2_connection = boto.ec2.connect_to_region(_get_region(zone))
    reservations = ec2_connection.get_all_instances(instance_ids=instance_ids)
    instances = []
    for reservation in reservations:
        instances.extend(reservation.instances)
    for instance in instances:
        print 'Bee %s: %s @ %s' % (instance.id, instance.state, instance.ip_address) 

def down():
    """
    Shutdown the load testing server.
    """
    username, key_name, zone, instance_ids = _read_server_list()
    if not instance_ids:
        print 'No bees have been mobilized.'
        return
    print 'Connecting to the hive.'
    ec2_connection = boto.ec2.connect_to_region(_get_region(zone))
    print 'Calling off the swarm.'
    terminated_instance_ids = ec2_connection.terminate_instances(
        instance_ids=instance_ids)
    print 'Stood down %i bees.' % len(terminated_instance_ids)
    _delete_server_list() 

def _get_ssh_client(params):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        params['instance_name'],
        username=params['username'],
        key_filename=_get_pem_path(params['key_name']))
    return client
    
def _ab_attack(params):
    client = _get_ssh_client(params)
    
    options = ''
    if params['headers'] is not '':
        for h in params['headers'].split(';'):
            options += ' -H "%s"' % h
    stdin, stdout, stderr = client.exec_command('tempfile -s .csv')
    params['csv_filename'] = stdout.read().strip()
    if params['csv_filename']:
        options += ' -e %(csv_filename)s' % params
    else:
        print 'Bee %i lost sight of the target (connection timed out creating csv_filename).' % params['i']
        return None
            
    if params['post_file']:
        _upload_to_instance(params['post_file'], params, '')
        options += ' -k -T "%(mime_type)s; charset=UTF-8" -p /tmp/honeycomb' % params
    params['options'] = options
    benchmark_command = 'ab -r -n %(num_requests)s -c %(concurrent_requests)s -C "sessionid=NotARealSessionID" %(options)s "%(url)s"' % params
    stdin, stdout, stderr = client.exec_command(benchmark_command)
    response = {}
    ab_results = stdout.read()
    ms_per_request_search = re.search('Time\ per\ request:\s+([0-9.]+)\ \[ms\]\ \(mean\)', ab_results)
    if not ms_per_request_search:
        print 'Bee %i lost sight of the target (connection timed out running ab).' % params['i']
        return None
    requests_per_second_search = re.search('Requests\ per\ second:\s+([0-9.]+)\ \[#\/sec\]\ \(mean\)', ab_results)
    failed_requests = re.search('Failed\ requests:\s+([0-9.]+)', ab_results)
    complete_requests_search = re.search('Complete\ requests:\s+([0-9]+)', ab_results)
    response['ms_per_request'] = float(ms_per_request_search.group(1))
    response['requests_per_second'] = float(requests_per_second_search.group(1))
    response['failed_requests'] = float(failed_requests.group(1))
    response['complete_requests'] = float(complete_requests_search.group(1))
    stdin, stdout, stderr = client.exec_command('cat %(csv_filename)s' % params)
    response['request_time_cdf'] = []
    for row in csv.DictReader(stdout):
        row["Time in ms"] = float(row["Time in ms"])
        response['request_time_cdf'].append(row)
    if not response['request_time_cdf']:
        print 'Bee %i lost sight of the target (connection timed out reading csv).' % params['i']
        return None
    print 'Bee %i is out of ammo.' % params['i']
    client.close()
    return response 

def _selenium_attack(params):
    """ 
        Runs selenium tests against the target url. 
	Built for concurrent use
    """
    client = _get_ssh_client(params)
    client.exec_command("mkdir /tmp/honeycomb")
    response = {}
    suite_path = "%s/*" % (params['selenium_suite'])
    #Upload the selenium test files to instance
    _upload_to_instance(suite_path, params, '')
    print 'Running Selenium attack on instance %i' % params['i']
    sel_cmd = 'DISPLAY=:1 xvfb-run java -jar /tmp/honeycomb/selenium-server-standalone-2.33.0.jar -htmlSuite "*firefox" "http://www.google.com" /tmp/honeycomb/Suite1.html /tmp/honeycomb/results.html'
    for x in range(0, params['num_requests']):	
 	#Run the selenium test on the machine
    	client.exec_command(sel_cmd)
    	dest_file = "%sresults_%s_%i.html" % ('/tmp/honeycomb/tests/', params['i'], x)
	print "Downloading file from instance: %s" % dest_file
    	_download_from_instance('/tmp/honeycomb/results.html', dest_file, params, '')
    client.close()
    return response 

def _print_ab_results(results, params, csv_filename):
    """
    Print summarized load-testing results.
    """
    timeout_bees = [r for r in results if r is None]
    exception_bees = [r for r in results if type(r) == socket.error]
    complete_bees = [r for r in results if r is not None and type(r) != socket.error]
    timeout_bees_params = [p for r,p in zip(results, params) if r is None]
    exception_bees_params = [p for r,p in zip(results, params) if type(r) == socket.error]
    complete_bees_params = [p for r,p in zip(results, params) if r is not None and type(r) != socket.error]
    num_timeout_bees = len(timeout_bees)
    num_exception_bees = len(exception_bees)
    num_complete_bees = len(complete_bees)
    if exception_bees:
        print ' %i of your bees didn\'t make it to the action. They might be taking a little longer than normal to find their machine guns, or may have been terminated without using "bees down".' % num_exception_bees
    if timeout_bees:
        print ' Target timed out without fully responding to %i bees.' % num_timeout_bees
    if num_complete_bees == 0:
        print ' No bees completed the mission. Apparently your bees are peace-loving hippies.'
        return
    complete_results = [r['complete_requests'] for r in complete_bees]
    total_complete_requests = sum(complete_results)
    print ' Complete requests:\t\t%i' % total_complete_requests
    complete_results = [r['failed_requests'] for r in complete_bees]
    total_failed_requests = sum(complete_results)
    print ' Failed requests:\t\t%i' % total_failed_requests
    complete_results = [r['requests_per_second'] for r in complete_bees]
    mean_requests = sum(complete_results)
    print ' Requests per second:\t%f [#/sec]' % mean_requests
    complete_results = [r['ms_per_request'] for r in complete_bees]
    mean_response = sum(complete_results) / num_complete_bees
    print ' Time per request:\t\t%f [ms] (mean of bees)' % mean_response
    # Recalculate the global cdf based on the csv files collected from ab. Can do this by sampling the request_time_cdfs for each of the completed bees in proportion to the number of 
    # complete_requests they have
    n_final_sample = 100
    sample_size = 100*n_final_sample
    n_per_bee = [int(r['complete_requests']/total_complete_requests*sample_size)
                 for r in complete_bees]
    sample_response_times = []
    for n, r in zip(n_per_bee, complete_bees):
        cdf = r['request_time_cdf']
        for i in range(n):
            j = int(random.random()*len(cdf))
            sample_response_times.append(cdf[j]["Time in ms"])
    sample_response_times.sort()
    request_time_cdf = sample_response_times[0:sample_size:sample_size/n_final_sample]
    print ' 50%% responses faster than:\t%f [ms]' % request_time_cdf[49]
    print ' 90%% responses faster than:\t%f [ms]' % request_time_cdf[89]
    if mean_response < 500:
        print 'Mission Assessment: Target crushed bee offensive.'
    elif mean_response < 1000:
        print 'Mission Assessment: Target successfully fended off the swarm.'
    elif mean_response < 1500:
        print 'Mission Assessment: Target wounded, but operational.'
    elif mean_response < 2000:
        print 'Mission Assessment: Target severely compromised.'
    else:
        print 'Mission Assessment: Swarm annihilated target.'
    if csv_filename:
        with open(csv_filename, 'w') as stream:
            writer = csv.writer(stream)
            header = ["% faster than", "all bees [ms]"]
            for p in complete_bees_params:
                header.append("bee %(instance_id)s [ms]" % p)
            writer.writerow(header)
            for i in range(100):
                row = [i, request_time_cdf[i]]
                for r in results:
                    row.append(r['request_time_cdf'][i]["Time in ms"])
                writer.writerow(row)

def _print_selenium_results(suite_path):
    print "Printing selenium results..."
    grep_path = '%s/results_*_*.html' % suite_path
    grep_passed_cmd = 'cat %s | grep -c "<td>passed</td>"' % grep_path
    grep_failed_cmd = 'cat %s | grep -c "<td>failed</td>"' % grep_path
    try:
    	passed = subprocess.check_output(grep_passed_cmd, shell=True)
	print "%s tests passed" % passed.rstrip()
    except:
	print 'No tests passed.'
    try:
    	failed = subprocess.check_output(grep_failed_cmd, shell=True)
	print "%s tests failed" % failed.rstrip()
    except:
    	print 'No tests failed.'
    #Clean up the results files
    os.system('rm -f %s' % grep_path)
    
def attack(url, n, c, **options):
    """
    Test the root url of this site.
    """
    username, key_name, zone, instance_ids = _read_server_list()
    headers = options.get('headers', '')
    selenium_suite = options.get('selenium_suite', '')
    csv_filename = options.get("csv_filename", '')
    if csv_filename:
        try:
            stream = open(csv_filename, 'w')
        except IOError, e:
            raise IOError("Specified csv_filename='%s' is not writable. Check permissions or specify a different filename and try again." % csv_filename)
    
    if not instance_ids:
        print 'No bees are ready to attack.'
        return
    print 'Connecting to the hive.'
    ec2_connection = boto.ec2.connect_to_region(_get_region(zone))
    print 'Assembling bees.'
    reservations = ec2_connection.get_all_instances(instance_ids=instance_ids)
    instances = []
    for reservation in reservations:
        instances.extend(reservation.instances)
    instance_count = len(instances)
    if n < instance_count * 2:
        print 'bees: error: the total number of requests must be at least %d (2x num. instances)' % (instance_count * 2)
        return
    if c < instance_count:
        print 'bees: error: the number of concurrent requests must be at least %d (num. instances)' % instance_count
        return
    if n < c:
        print 'bees: error: the number of concurrent requests (%d) must be at most the same as number of requests (%d)' % (c, n)
        return
    requests_per_instance = int(float(n) / instance_count)
    connections_per_instance = int(float(c) / instance_count)
    print 'Each of %i bees will fire %s rounds, %s at a time.' % (instance_count, requests_per_instance, connections_per_instance)
    params = []
    for i, instance in enumerate(instances):
        params.append({
            'i': i,
            'instance_id': instance.id,
            'instance_name': instance.public_dns_name,
            'url': url,
            'concurrent_requests': connections_per_instance,
            'num_requests': requests_per_instance,
            'username': username,
            'key_name': key_name,
            'headers': headers,
            'selenium_suite': selenium_suite,
            'post_file': options.get('post_file'),
            'mime_type': options.get('mime_type', ''),
        })
    print 'Stinging URL so it will be cached for the attack.'
    # Ping url so it will be cached for testing
    dict_headers = {}
    if headers is not '':
        dict_headers = headers = dict(h.split(':') for h in headers.split(';'))
    request = urllib2.Request(url, headers=dict_headers)
    urllib2.urlopen(request).read()
    print 'Organizing the swarm.'
    
    results = []
    
    try:
        pool = Pool(len(params))
        if selenium_suite:
            print 'Running Selenium attack...'
            results = pool.map(_selenium_attack, params)
            _print_selenium_results(selenium_suite)
        else:
            print 'Running AB attack...'
            results = pool.map(_ab_attack, params)
            _print_ab_results(results, params, csv_filename)
    except socket.error, e:
        return e
    print 'Offensive complete.'
    print 'The swarm is awaiting new orders....'
