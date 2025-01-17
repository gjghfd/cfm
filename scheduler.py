#!/usr/bin/python3
"""Scheduler connects to all servers"""

from __future__ import print_function
import logging
import argparse
import random
import time
import functools
import json
import statistics

import grpc

from protocol import protocol_pb2
from protocol import protocol_pb2_grpc

import pandas as pd

import lib.workloads

MAIN_LOOP_SLEEP = 0.1 # 100 ms
SAMPLE_FREQ = 1 * 1000  # 1 secs in ms

class Scheduler:
    def __init__(self, args, variable_ratios):
        # Instantiate Servers
        self.wid = 0
        self.servers = []
        random.seed(args.seed)
        self.schedule = self.get_schedule(args.workload_path, args.workload)
        self.pending = [] # Workloads that have arrived but haven't been scheduled
        self.executing = {} # Currently executing workloads
        self.finished = [] # Workloads that have finished executing

        self.remotemem = args.remotemem
        self.max_far_mem = args.max_far
        self.base_time = time.time()
        n = len(args.servers)
        print('num servers = {}'.format(n))

        sum_cpu = 0
        for c in args.each_cpu:
            sum_cpu = sum_cpu + c
        
        for index, addr in enumerate(sorted(args.servers)):
            ratio = args.each_cpu[index] / args.cpus
            self.servers.append(Server(addr, args.remotemem, args.each_cpu[index], int(args.mem * ratio),
                                  args.uniform_ratio, variable_ratios,
                                  int(args.max_far * args.each_cpu[index] / sum_cpu), args.optimal))
        
        self.original_servers = list(self.servers) # Retain the original ordering for later shuffling operations

    
    def get_schedule(self, workload_path, workloads):
        invocations = pd.read_csv(workload_path, usecols=['submit_time', 'function_id', 'memory', 'task_id'])
        schedule = []
        for index, row in invocations.iterrows():
            func_id = int(row['function_id']) - 1
            workload_name = workloads[func_id]
            workload_class = lib.workloads.get_workload_class(workloads[func_id])
            cpu_req = workload_class.cpu_req
            ideal_mem = workload_class.ideal_mem
            slo = workload_class.slo

            schedule.append(SchedWorkload(workload_name, index + 1, cpu_req, ideal_mem,
                                          row['submit_time'] / 1000.0, workload_class.min_mem, slo))
            
        schedule.sort(key=lambda x: x.ts_arrival)
        base_time = schedule[0].ts_arrival - 1
        for request in schedule:
            request.ts_arrival -= base_time
            request.ddl -= base_time
        print('Workloads Info:')
        print(len(schedule))
        print(schedule[0].ts_arrival, flush = True)
        return schedule

    def update_resources(self):
        for s in self.servers:
            s.get_resources()

    def find_server_fits(self, workload):
        if not self.servers:
            return None

        # first try to fit the workload normally
        for s in self.servers:
            if s.fits_normally(workload):
                return s

        # normal placement didn't work, are we using remote memory?
        if not self.remotemem:
            return None

        # we are using remote memory. for every server, check if we
        # can fit it using remote mem
        for s in self.servers:
            if s.fits_remotemem(workload):
                return s

        return None

    def start_schedule(self):
        print("Will execute {} tasks.".format(len(self.schedule)))

        while self.schedule or self.pending or self.executing:

            ''' Update the Server instances with the latest resource information from their
                server.py counterparts'''
            self.update_resources()

            # move workloads from schedule to pendingq when they arrive
            if self.schedule:
                self.schedule = self.move_to_pending()

            # move from pendingq to executing when we place them on a server
            if self.pending:
                successfully_executed = self.exec_one()
                if successfully_executed:
                    self.servers = list(self.original_servers)
                    random.shuffle(self.servers)

            if not self.pending and self.schedule:
                pass

            # move from executing to finishq when they finish execution
            if self.executing:
                self.check_finished()

            time.sleep(MAIN_LOOP_SLEEP)

        return self.finished

    def exec_one(self):
        """ check if any machine fits the workload.
        each server can fit one new workload per exec_one() call. """
        servers = list(self.servers)
        futures = [] # list of tuples (future, workload, server)

        def execute_done(future, base_time, workload, executing, server):
            assert future.result().success
            workload.ts_sent = time.time() - base_time
            print("Sent {} to {}".format(workload.get_name(), server.name), flush = True)
            executing[workload.idd] = workload

        for workload in list(self.pending):
            s = self.find_server_fits(workload)
            if s:
                future = s.execute_future(workload)
                futures.append((future, workload, s))
                self.pending.remove(workload)
                servers.remove(s)
                future.add_done_callback(functools.partial(execute_done,
                            base_time=self.base_time, workload=workload, executing=self.executing, server=s))
                return True
        return False

    def move_to_pending(self):
        """ returns a new scheduleq with the workloads that couldn't be
        scheduled"""
        elapsed = time.time() - self.base_time

        new_schedule = []
        for workload in self.schedule:
            if workload.ts_arrival <= elapsed:
                self.pending.append(workload)
                print("{} arrived".format(workload.name + str(workload.idd)), flush = True)
            else:
                new_schedule.append(workload)

        return new_schedule

    def check_finished(self):
        for s in self.servers:
            finish_times, start_times = s.get_finished()
            for idd in finish_times.keys():
                workload = self.executing[idd]
                workload.ts_start = start_times[idd]
                workload.ts_finish = finish_times[idd]
                self.finished.append(workload)
                del self.executing[idd]
        


class SchedWorkload:
    def __init__(self, name, idd, cpu_req, mem_req, ts_arrival, min_mem, slo):
        self.name = name
        self.idd = idd
        self.cpu_req = cpu_req
        self.mem_req = mem_req
        self.min_mem = min_mem

        self.ts_arrival = ts_arrival
        self.ts_sent = 0
        self.ts_start = 0
        self.ts_finish = 0

        self.ddl = self.ts_arrival + slo

    def get_name(self):
        return self.name + str(self.idd)

    def get_duration(self):
        return self.ts_finish - self.ts_start

    def get_slo(self):
        if self.ts_finish <= self.ddl:
            return 0
        return 1

    def get_jct(self):
        return self.ts_finish - self.ts_arrival


class Server:
    def __init__(self, addr, remotemem, max_cpus, max_mem,
                 uniform_ratio, variable_ratios,
                 max_far, optimal):
        self.channel = grpc.insecure_channel(addr)
        self.stub = protocol_pb2_grpc.SchedulerStub(self.channel)
        self.checkin(remotemem, max_cpus, max_mem, uniform_ratio,
                     variable_ratios, max_far > 0, optimal)
        self.max_far = max_far
        self.addr = addr

        print("connected to server={}".format(self.name), flush = True)

    def __del__(self):
        self.close()

    def checkin(self, remotemem, max_cpus, max_mem,
                uniform_ratio, variable_ratios,
                limit_remote_mem, optimal):
        """ returns the server name if successful """
        
        self.remotemem = remotemem
        self.free_cpus = max_cpus
        self.total_cpus = max_cpus
        self.free_mem = max_mem
        self.total_mem = max_mem
        self.uniform_ratio = uniform_ratio
        self.variable_ratios = variable_ratios

        req = protocol_pb2.CheckinReq(use_remote_mem=remotemem,
                                      max_cpus=max_cpus,
                                      max_mem=max_mem,
                                      uniform_ratio=uniform_ratio,
                                      variable_ratios=variable_ratios,
                                      limit_remote_mem=limit_remote_mem,
                                      optimal=optimal)
        reply = self.stub.checkin(req)
        if not reply.success:
            raise RuntimeError("Not enough memory or cpus")

        self.name = reply.server_name


    def close(self):
        req = protocol_pb2.ShutdownReq()
        _ = self.stub.shutdown(req)
        self.channel.close()

    def execute_future(self, workload):
        """ returns a future of the execution request """
        req = protocol_pb2.ExecuteReq(wname=workload.name, idd=workload.idd)
        return self.stub.execute.future(req)

    def get_resources(self):
        req = protocol_pb2.GetResourcesReq()
        reply = self.stub.get_resources(req)
        self.free_cpus = reply.free_cpus
        self.alloc_mem = reply.alloc_mem
        self.min_mem_sum = reply.min_mem_sum

    def fits_farmem_uniform(self, w, max_far_mem, total_far_mem):
        """ assumes everything from fits_remotemem() plus the workload
        fits in cpus """
        local_alloc_mem = self.alloc_mem + w.mem_req
        local_ratio = min(1, self.total_mem / local_alloc_mem)
        if local_ratio < self.uniform_ratio:
            return False

        # check if (1 - local_ratio) that makes the incoming job fit results in
        # a far memory usage above the max
        if max_far_mem > 0:
            additional_far_mem = (1 - local_ratio) * w.mem_req
            if additional_far_mem + total_far_mem > max_far_mem:
                return False
        return True

    def fits_farmem_variable(self, w):
        local_min_mem_sum = self.min_mem_sum + w.min_mem
        if local_min_mem_sum > self.total_mem:
            return False
        
        if self.max_far > 0:
            curr_far_mem = max(0, self.alloc_mem - self.total_mem)
            if curr_far_mem > 0:
                additional_far_mem = w.mem_req
            else:
                additional_far_mem = max(0, w.mem_req + self.alloc_mem - self.total_mem)

            if curr_far_mem + additional_far_mem > self.max_far:
                return False
        return True


    def fits_remotemem(self, w):
        """ assumes the workload didn't fit normally, try to fit it with
        remote memory. we only want to determine whether the workload fits,
        but will let the server compute its own ratio (to avoid consistency
        issues).
        others_far_mem is the far memory in use minus far memory used
        by this server. """
        if not self.fits_cpu_remote(w):
            return False

        # if self.uniform_ratio:
        #     return self.fits_farmem_uniform(w, max_far_mem, total_far_mem)

        # Variable Policy
        return self.fits_farmem_variable(w)


    def fits_normally(self, w):
        free_mem = self.total_mem - self.alloc_mem
        return self.fits_cpu(w) and free_mem >= w.mem_req

    def fits_cpu(self, w):
        return self.free_cpus >= w.cpu_req

    def fits_cpu_remote(self, w):
        return self.free_cpus >= w.cpu_req      # do not care reclaimer cpu
        # return self.free_cpus - 1 >= w.cpu_req

    def get_finished(self):
        req = protocol_pb2.GetFinishedReq()
        finished = self.stub.get_finished(req)
        return (finished.finished_times, finished.start_times)

    def get_samples(self):
        req = protocol_pb2.GetSamplesReq()
        samples = self.stub.get_samples(req)
        return samples


def print_finished_stats(finishq, base_time):
    num = len(finishq)
    print("\nfinished {} workloads".format(num), flush = True)
    latest_finish = max(map(lambda w: w.ts_finish, finishq))
    print("makespan={}".format(round(latest_finish, 3)), flush = True)
    print("\nName,Arrival,Start,Finish", flush = True)
    total_jct = 0
    total_slo = 0
    for workload in sorted(finishq, key=lambda w: w.get_name()):
        jct = workload.get_jct()
        slo = workload.get_slo()
        print("{},{},{},{},{},{},{}".format(workload.get_name(),
                                   round(workload.ts_arrival, 3),
                                   round(workload.ts_sent, 3),
                                   round(workload.ts_finish, 3),
                                   round(workload.ddl, 3),
                                   round(jct, 3),
                                   slo), flush = True)
        total_jct += jct
        total_slo += slo
    print("AJCT = {}, SOLV = {}".format(total_jct / num, total_slo), flush = True)

def average_samples_by_time(sample_list): # Takes in a list of lists
    # '*' unpacks an iterable into multiple args for a function
    tuples_by_time = zip(*sample_list)

    # Compute the mean for each time step
    means = map(statistics.mean, tuples_by_time)

    return means

def sum_samples_by_time(sample_list): # Takes in a list of lists
    # '*' unpacks an iterable into multiple args for a function
    tuples_by_time = zip(*sample_list)

    # Compute the mean for each time step
    sums = map(sum, tuples_by_time)

    return sums

def combine_samples(servers):
    mem_samples = list()
    cpu_samples = list()
    swap_samples = dict()
    bw_in_samples = dict()
    bw_out_samples = dict()
    bytes_in_samples = list()
    bytes_out_samples = list()
    curr_pages_samples = dict()

    # Compose of list of lists
    for s in servers:
        samples = s.get_samples()
        mem_samples.append(samples.mem_util)
        cpu_samples.append(samples.cpu_util)
        swap_samples[s.addr] = samples.swap_util
        bw_in_samples[s.addr] = samples.bw_in
        bw_out_samples[s.addr] = samples.bw_out
        bytes_in_samples.append(samples.bytes_in)
        bytes_out_samples.append(samples.bytes_out)
        curr_pages_samples[s.addr] = samples.curr_pages


    # Get the maximum run time
    max_len = max(map(len, mem_samples))

    # Padding each list so that they're all the same length
    [lst.extend([0]*(max_len - len(lst))) for lst in mem_samples]
    [lst.extend([0]*(max_len - len(lst))) for lst in cpu_samples]

    # Averaging the samples at each time step
    mem = average_samples_by_time(mem_samples)
    cpu = average_samples_by_time(cpu_samples)

    # Round values
    rounded_mem = map(lambda num: round(num, 3), mem)
    rounded_cpu = map(lambda num: round(num, 3), cpu)
    swap_samples = {s: list(map(lambda num: round(num, 3), lst)) for s, lst in swap_samples.items()}
    bw_out_samples = {s: list(map(lambda num: round(num, 3), lst)) for s, lst in bw_out_samples.items()}
    bw_in_samples = {s: list(map(lambda num: round(num, 3), lst)) for s, lst in bw_in_samples.items()}
    curr_pages_samples = {s: list(lst) for s, lst in curr_pages_samples.items()}

    return (rounded_mem, rounded_cpu, bw_in_samples, bw_out_samples,
            swap_samples, bytes_in_samples, bytes_out_samples, curr_pages_samples)

def write_samples_to_file(filename, samples):
    mem, cpu, bw_in, bw_out, swap, bytes_in, bytes_out, curr_pages = samples

    with open(filename, 'w') as f:
        combined = zip(mem, cpu)
        combined = [{'Mem':m, 'CPU':c}
                      for m,c in combined]
        numbered = dict(enumerate(combined))
        numbered['bytes in'] = sum(bytes_in)
        numbered['bytes out'] = sum(bytes_out)
        numbered['swap samples'] = swap
        numbered['bw out'] = bw_out
        numbered['bw in'] = bw_in
        numbered['curr_pages'] = curr_pages
        f.write(json.dumps(numbered, indent=4))

def generate_filename(args):
    cpus = str(args.cpus)
    mem = str(args.mem)
    size = str(args.size)
    policy = "optimal"

    filename = 'cpus_{}_mem_{}_size_{}'
    filename = filename.format(cpus, mem, size)
    if args.uniform_ratio != None:
        filename += '_uniform_ratio_{}'.format(args.uniform_ratio)

    filename += '_policy_{}'.format(policy)
    cur_time = time.localtime()
    time_string = '_{}-{}-{}:{}:{}:{}'.format(cur_time.tm_year, cur_time.tm_mon,
                                              cur_time.tm_mday, cur_time.tm_hour,
                                              cur_time.tm_min, cur_time.tm_sec)
    filename += time_string + '.json'
    return filename

def check_args(args):
    if not args.remotemem:
        assert(not args.uniform_ratio), "uniform_ratio must be used with remote memory"
        assert(not args.variable_ratios), "variable_ratio must be used with remote memory"
        assert(not args.optimal), "optimal must be used with remote memory"
    else:
        # No two of these three can be active simultaneously
        uniform, variable, optimal = map(bool, (args.uniform_ratio, args.variable_ratios, args.optimal))
        print(uniform, variable, optimal, flush = True)
        assert(uniform ^ variable ^ optimal),\
               ("You must specify one (and only one) of the following options: "
                "uniform_ratio, variable_ratio.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', type=int,
                        help="Used to seed randomization",
                        default=42)
    parser.add_argument('servers', type=lambda s: s.split(','),
                        help='comma separated list of servers')
    parser.add_argument('--each_cpu', type=lambda s: s.split(','),
                        help='comma separated list of cpus on each server',
                        default=[16,16,16,16,16,16,16,16,16,16,16,16,16,16,16,16])
    parser.add_argument('--cpus', type=int,
                        help='number of cpus required for each server',
                        default=16)
    parser.add_argument('--mem', type=int,
                        help='memory required for each server (MB)',
                        default=65536)
    parser.add_argument('--remotemem', '-r', action='store_true',
                        help='enable remote memory',
                        default=True)
    parser.add_argument('--max_far', '-s', type=int, default=16384,
                        help='max size of far memory, default=16384')
    parser.add_argument('--size', type=int,
                        help='size of workload (num of tasks) ' \
                        'default=200', default=200)
    parser.add_argument('--workload', type=lambda s: s.split(','),
                        help='tasks that comprise the workload ' \
                        'default=matrix,graphx,pagerank,imgscan,quicksort,memcached',
                        default='matrix,graphx,pagerank,imgscan,quicksort,memcached')
    parser.add_argument('--uniform_ratio', type=float,
                        help='Smallest allowable memory ratio')
    parser.add_argument('--variable_ratios', type= lambda s: s.split(','),
                        help='Min ratio for each workload')
    parser.add_argument('--optimal', '-o', action='store_true',
                        help='Use the optimal algorithm', default=True)
    parser.add_argument('--workload_path', type=str,
                        help='Workload path',
                        default='/mydata/cfm/workload.csv')

    cmdargs = parser.parse_args()

    # Check for options that shouldn't be used together
    check_args(cmdargs)

    # Put the workload_ratio values in a dictionary with the corresponding name
    if cmdargs.variable_ratios:
        assert len(cmdargs.variable_ratios) == len(cmdargs.workload)
        variable_ratios = map(float, cmdargs.variable_ratios)
        variable_ratios = dict(zip(cmdargs.workload, variable_ratios))
    else:
        variable_ratios = dict()

    try:
        scheduler = Scheduler(cmdargs, variable_ratios)
        finished = scheduler.start_schedule()
        filename = generate_filename(cmdargs)
        print_finished_stats(finished, scheduler.base_time)
        samples = combine_samples(scheduler.servers)
        write_samples_to_file(filename, samples)
    except KeyboardInterrupt:
        for s in scheduler.servers[:]:
            del s

if __name__ == '__main__':
    logging.basicConfig()
    main()
