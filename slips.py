#!/usr/bin/python -u
# This file is part of the Stratosphere Linux IPS
# See the file 'LICENSE' for copying permission.
# Author: Sebastian Garcia. eldraco@gmail.com , sebastian.garcia@agents.fel.cvut.cz

import sys
from colors import *
from datetime import datetime
from datetime import timedelta
import argparse
import multiprocessing
from multiprocessing import Queue
import time
from modules.markov_models_1 import __markov_models__

version = '0.3alpha'

###################
class Tuple(object):
    """ The class to simply handle tuples """
    def __init__(self, tuple4, anonymize=False):
        self.id = tuple4
        self.anonymize = anonymize
        self.amount_of_flows = 0
        self.src_ip = tuple4.split('-')[0]
        self.dst_ip = tuple4.split('-')[1]
        self.protocol = tuple4.split('-')[3]
        self.state_so_far = ""
        self.winner_model_id = False
        self.winner_model_distance = float('inf')
        self.proto = ""
        self.datetime = ""
        self.T1 = False
        self.T2 = False
        self.TD = False
        self.current_size = -1
        self.current_duration = -1
        self.previous_size = -1
        self.previous_duration = -1
        self.previous_time = -1
        # Thresholds
        self.tto = timedelta(seconds=3600)
        self.tt1 = float(1.05)
        self.tt2 = float(1.3)
        self.tt3 = float(5)
        self.td1 = float(0.1)
        self.td2 = float(10)
        self.ts1 = float(250)
        self.ts2 = float(1100)
        # The state
        self.state = ""
        # Final values for getting the state
        self.duration = -1
        self.size = -1
        self.periodic = -1
        self.color = str
        # By default print all tuples. Depends on the arg
        self.should_be_printed = True
        self.desc = ''
        self.detected_label = False

    def set_detected_label(self, label):
        self.detected_label = label

    def unset_detected_label(self):
        self.detected_label = False

    def get_detected_label(self):
        return self.detected_label

    def get_src_ip(self):
        return self.src_ip

    def set_original_src_ip(self, orig_src_ip):
        self.original_src_ip = orig_src_ip

    def get_original_src_ip(self):
        return self.original_src_ip

    def get_protocol(self):
        return self.protocol

    def get_state(self):
        return self.state

    def set_verbose(self, verbose):
        self.verbose = verbose

    def get_whois_data(self):
        try:
            import ipwhois
        except ImportError:
            print 'The ipwhois library is not install. pip install ipwhois'
            return False
        # is the ip in the cache
        try:
            self.desc = whois_cache[self.dst_ip]
        except KeyError:
            # Is not, so just ask for it
            try:
                obj = ipwhois.IPWhois(self.dst_ip)
                data = obj.lookup()
                self.desc = data['nets'][0]['description'].strip().replace('\n',' ') + ',' + data['nets'][0]['country']
            except ipwhois.IPDefinedError as e:
                if 'Multicast' in e:
                    self.desc = 'Multicast'
                self.desc = 'Private Use'
            except ValueError:
                # Not a real IP, maybe a MAC
                pass
            # Store in the cache
            whois_cache[self.dst_ip] = self.desc

    def add_new_flow(self, column_values):
        """ Add new stuff about the flow in this tuple """
        # 0:starttime, 1:dur, 2:proto, 3:saddr, 4:sport, 5:dir, 6:daddr: 7:dport, 8:state, 9:stos,  10:dtos, 11:pkts, 12:bytes
        # Store previous
        self.previous_size = self.current_size
        self.previous_duration = self.current_duration
        self.previous_time = self.datetime
        if self.verbose > 2:
            print '\nAdding flow {}'.format(column_values)
        # Get the starttime
        #self.datetime = datetime.strptime(column_values[0], '%Y/%m/%d %H:%M:%S.%f')
        self.datetime = datetime.strptime(column_values[0], '%Y-%m-%d %H:%M:%S.%f')
        # Get the size
        try:
            self.current_size = float(column_values[12])
        except ValueError:
            # It can happend that we dont have this value in the binetflow
            self.current_size = 0.0
        # Get the duration
        try:
            self.current_duration = float(column_values[1])
        except ValueError:
            # It can happend that we dont have this value in the binetflow
            self.current_duration = 0.0
        # Get the proto
        self.proto = str(column_values[2])
        # Get the amount of flows
        self.amount_of_flows += 1
        # Update value of T1
        self.T1 = self.T2
        try:
            # Update value of T2
            self.T2 = self.datetime - self.previous_time
            # Are flows sorted?
            if self.T2.total_seconds() < 0:
                # Flows are not sorted
                if self.verbose > 2:
                    print '@',
                # What is going on here when the flows are not ordered?? Are we losing flows?
        except TypeError:
            self.T2 = False
        # Compute the rest
        self.compute_periodicity()
        self.compute_duration()
        self.compute_size()
        self.compute_state()
        self.compute_symbols()
        self.do_print()
        if self.verbose > 1:
            print '\tTuple {}. Amount of flows so far: {}'.format(self.get_id(), self.amount_of_flows)


    def compute_periodicity(self):
        # If either T1 or T2 are False
        if (isinstance(self.T1, bool) and self.T1 == False) or (isinstance(self.T2, bool) and self.T2 == False):
            self.periodicity = -1
        elif self.T2 >= self.tto:
            t2_in_hours = self.T2.total_seconds() / self.tto.total_seconds()
            # Should be int always
            for i in range(int(t2_in_hours)):
                self.state += '0'
        elif self.T1 >= self.tto:
            t1_in_hours = self.T1.total_seconds() / self.tto.total_seconds()
            # Should be int always
            for i in range(int(t1_in_hours)):
                self.state += '0'
        if not isinstance(self.T1, bool) and not isinstance(self.T2, bool):
            try:
                if self.T2 >= self.T1:
                    self.TD = timedelta(seconds=(self.T2.total_seconds() / self.T1.total_seconds())).total_seconds()
                else:
                    self.TD = timedelta(seconds=(self.T1.total_seconds() / self.T2.total_seconds())).total_seconds()
            except ZeroDivisionError:
                self.TD = 1
            # Decide the periodic based on TD and the thresholds
            if self.TD <= self.tt1:
                # Strongly periodic
                self.periodic = 1
            elif self.TD < self.tt2:
                # Weakly periodic
                self.periodic = 2
            elif self.TD < self.tt3:
                # Weakly not periodic
                self.periodic = 3
            else:
                self.periodic = 4
        if self.verbose > 2:
            print '\tPeriodic: {}'.format(self.periodic)

    def compute_duration(self):
        if self.current_duration <= self.td1:
            self.duration = 1
        elif self.current_duration > self.td1 and self.current_duration <= self.td2:
            self.duration = 2
        elif self.current_duration > self.td2:
            self.duration = 3
        if self.verbose > 2:
            print '\tDuration: {}'.format(self.duration)

    def compute_size(self):
        if self.current_size <= self.ts1:
            self.size = 1
        elif self.current_size > self.ts1 and self.current_size <= self.ts2:
            self.size = 2
        elif self.current_size > self.ts2:
            self.size = 3
        if self.verbose > 2:
            print '\tSize: {}'.format(self.size)

    def compute_state(self):
        if self.periodic == -1:
            if self.size == 1:
                if self.duration == 1:
                    self.state += '1'
                elif self.duration == 2:
                    self.state += '2'
                elif self.duration == 3:
                    self.state += '3'
            elif self.size == 2:
                if self.duration == 1:
                    self.state += '4'
                elif self.duration == 2:
                    self.state += '5'
                elif self.duration == 3:
                    self.state += '6'
            elif self.size == 3:
                if self.duration == 1:
                    self.state += '7'
                elif self.duration == 2:
                    self.state += '8'
                elif self.duration == 3:
                    self.state += '9'
        elif self.periodic == 1:
            if self.size == 1:
                if self.duration == 1:
                    self.state += 'a'
                elif self.duration == 2:
                    self.state += 'b'
                elif self.duration == 3:
                    self.state += 'c'
            elif self.size == 2:
                if self.duration == 1:
                    self.state += 'd'
                elif self.duration == 2:
                    self.state += 'e'
                elif self.duration == 3:
                    self.state += 'f'
            elif self.size == 3:
                if self.duration == 1:
                    self.state += 'g'
                elif self.duration == 2:
                    self.state += 'h'
                elif self.duration == 3:
                    self.state += 'i'
        elif self.periodic == 2:
            if self.size == 1:
                if self.duration == 1:
                    self.state += 'A'
                elif self.duration == 2:
                    self.state += 'B'
                elif self.duration == 3:
                    self.state += 'C'
            elif self.size == 2:
                if self.duration == 1:
                    self.state += 'D'
                elif self.duration == 2:
                    self.state += 'E'
                elif self.duration == 3:
                    self.state += 'F'
            elif self.size == 3:
                if self.duration == 1:
                    self.state += 'G'
                elif self.duration == 2:
                    self.state += 'H'
                elif self.duration == 3:
                    self.state += 'I'
        elif self.periodic == 3:
            if self.size == 1:
                if self.duration == 1:
                    self.state += 'r'
                elif self.duration == 2:
                    self.state += 's'
                elif self.duration == 3:
                    self.state += 't'
            elif self.size == 2:
                if self.duration == 1:
                    self.state += 'u'
                elif self.duration == 2:
                    self.state += 'v'
                elif self.duration == 3:
                    self.state += 'w'
            elif self.size == 3:
                if self.duration == 1:
                    self.state += 'x'
                elif self.duration == 2:
                    self.state += 'y'
                elif self.duration == 3:
                    self.state += 'z'
        elif self.periodic == 4:
            if self.size == 1:
                if self.duration == 1:
                    self.state += 'R'
                elif self.duration == 2:
                    self.state += 'S'
                elif self.duration == 3:
                    self.state += 'T'
            elif self.size == 2:
                if self.duration == 1:
                    self.state += 'U'
                elif self.duration == 2:
                    self.state += 'V'
                elif self.duration == 3:
                    self.state += 'W'
            elif self.size == 3:
                if self.duration == 1:
                    self.state += 'X'
                elif self.duration == 2:
                    self.state += 'Y'
                elif self.duration == 3:
                    self.state += 'Z'

    def compute_symbols(self):
        if not isinstance(self.T2, bool):
            if self.T2 <= timedelta(seconds=5):
                self.state += '.'
            elif self.T2 <= timedelta(seconds=60):
                self.state += ','
            elif self.T2 <= timedelta(seconds=300):
                self.state += '+'
            elif self.T2 <= timedelta(seconds=3600):
                self.state += '*'
        if self.verbose > 2:
            print '\tTD:{}, T2:{}, T1:{}, State: {}'.format(self.TD, self.T2, self.T1, self.state)

    def get_id(self):
        return self.id

    def __repr__(self):
        return('{} [{}] ({}): {}'.format(self.color(self.get_id()), self.desc, self.amount_of_flows, self.state))

    def print_tuple_detected(self):
        """
        Print the tuple. The state is the state since the last detection of the tuple. Not everything
        """
        return('{} [{}] ({}): {}  Detected as: {}'.format(self.color(self.get_id()), self.desc, self.amount_of_flows, self.get_state(), self.get_detected_label()))

    def set_color(self, color):
        self.color = color

    def dont_print(self):
        if self.verbose > 3:
            print '\tDont print tuple {}'.format(self.get_id())
        self.should_be_printed = False

    def do_print(self):
        self.should_be_printed = True
        if self.verbose > 3:
            print '\tPrint tuple {}'.format(self.get_id())






# Process
###########
###########
class Processor(multiprocessing.Process):
    """ A class process to run the process of the flows """
    def __init__(self, queue, slot_width, only_detections, get_whois, verbose, amount, dontdetect, anonymize):
        multiprocessing.Process.__init__(self)
        self.only_detections = only_detections
        self.get_whois = get_whois
        self.verbose = verbose
        # The amount of letters requested to print minimum
        self.amount = amount
        self.queue = queue
        self.tuples = {}
        self.slot_starttime = -1
        self.slot_endtime = -1
        self.slot_width = slot_width
        self.dontdetect = dontdetect
        self.amount_of_tuple_in_this_time_slot = 0
        # To know if we should export the 
        self.anonymize = anonymize

    def get_tuple(self, tuple4, orig_src_ip=False):
        """ Get the values and return the correct tuple for them """
        try:
            tuple = self.tuples[tuple4]
        except KeyError:
            # First time for this connection
            tuple = Tuple(tuple4, self.anonymize)
            tuple.set_verbose(self.verbose)
            if self.anonymize and orig_src_ip:
                tuple.set_original_src_ip(orig_src_ip)
            self.tuples[tuple.get_id()] = tuple
        return tuple

    def process_out_of_time_slot(self, column_values):
        """
        Process the tuples when we are out of the time slot
        """
        try:
            # Outside the slot
            if self.verbose:
                self.amount_of_tuple_in_this_time_slot = len(self.tuples) - self.amount_of_tuple_in_this_time_slot
                print cyan('Slot Started: {}, finished: {}. ({} tuples)'.format(self.slot_starttime, self.slot_endtime, self.amount_of_tuple_in_this_time_slot))
                for tuple4 in self.tuples:
                    tuple = self.get_tuple(tuple4)
                    if tuple.amount_of_flows >= self.amount and tuple.should_be_printed:
                        if not tuple.desc and self.get_whois:
                            tuple.get_whois_data()
                        print tuple.print_tuple_detected()
                    # Clear the color because we already print it
                    if tuple.color == red:
                        tuple.set_color(yellow)
                    # After printing the tuple in this time slot, we should not print it again unless we see some of its flows.
                    if tuple.should_be_printed:
                        tuple.dont_print()
            # After each timeslot finishes forget the tuples that are too big. This is useful when a tuple has a very very long state that is not so useful to us. Later we forget it when we detect it or after a long time.
            ids_to_delete = []
            for tuple in self.tuples:
                if self.tuples[tuple].amount_of_flows > 100:
                    if self.verbose > 3:
                        print 'Delete all the letters of {} because there were more than 100. Start again with this tuple.'.format(self.tuples[tuple].get_id())
                    ids_to_delete.append(self.tuples[tuple].get_id())
            # Actually delete them
            for id in ids_to_delete:
                del self.tuples[id]
            # Move the time slot
            #self.slot_starttime = datetime.strptime(column_values[0], '%Y/%m/%d %H:%M:%S.%f')
            self.slot_starttime = datetime.strptime(column_values[0], '%Y-%m-%d %H:%M:%S.%f')
            self.slot_endtime = self.slot_starttime + self.slot_width

            # Put the last flow received in the next slot, because it overcommed the threshold and it was not processed
            tuple4 = column_values[3]+'-'+column_values[6]+'-'+column_values[7]+'-'+column_values[2]
            srcip = False
            if self.anonymize:
                # Hash the IP 
                srcip = tuple4.split('-')[0]
                dstip = tuple4.split('-')[1]
                dstport = tuple4.split('-')[2]
                proto = tuple4.split('-')[3]
                t_hashed_ip = hashlib.md5()
                t_hashed_ip.update(srcip)
                hash_src_ip = t_hashed_ip.hexdigest()
                tuple4 = hash_src_ip + '-' + dstip + '-' + dstport + '-' + proto
            # Get the tuple, but store the original src ip if we create a new tuple
            tuple = self.get_tuple(tuple4, orig_src_ip=srcip)
            if self.verbose:
                if len(tuple.state) == 0:
                    tuple.set_color(red)
            tuple.add_new_flow(column_values)
            # Detect the first flow of the future timeslow
            self.detect(tuple)
        except Exception as inst:
            print '\tProblem with process_out_of_time_slot()'
            print type(inst)     # the exception instance
            print inst.args      # arguments stored in .args
            print inst           # __str__ allows args to printed directly
            sys.exit(1)

    def detect(self, tuple):
        """
        Detect behaviors
        """
        try:
            if not self.dontdetect:
                (detected, label, matching_len) = __markov_models__.detect(tuple, self.verbose)
                if detected:
                    # Change color
                    tuple.set_color(magenta)
                    # Set the detection label
                    tuple.set_detected_label(label)
                    """
                    # Set the detection state len
                    tuple.set_best_model_matching_len(statelen)
                    """
                    if self.verbose > 5:
                        print 'Last flow: Detected with {}'.format(label)
                    # Play sound
                    if args.sound:
                        pygame.mixer.music.play()
                elif not detected and self.only_detections:
                    # Not detected by any reason. No model matching but also the state len is too short.
                    tuple.unset_detected_label()
                    if self.verbose > 5:
                        print 'Last flow: Not detected'
                    tuple.dont_print()
        except Exception as inst:
            print '\tProblem with detect()'
            print type(inst)     # the exception instance
            print inst.args      # arguments stored in .args
            print inst           # __str__ allows args to printed directly
            sys.exit(1)

    def convert(self, values):
        """ Convert from the other format to binetflow """
        # other format
            #0:client, 1:ip_local, 2:ip_remote, 3:port_local, 4:port_remote, 5:proto, 6:start_in, 7:start_out, 8:stop_in, 9:stop_out, 10:size_in, 11:size_out, 12:count_in, 13:count_out, 14:seen_start_in, 15:seen_start_out, 16:tag
        # binetflow format
            #0:starttime, 1:dur, 2:proto, 3:saddr, 4:sport, 5:dir, 6:daddr: 7:dport, 8:state, 9:stos,  10:dtos, 11:pkts, 12:bytes
        column_values = [False,False,False,False,False,False,False,False,False,False,False,False,False]
        # bytes
        # We first do the bytes so we can detect when the field is empty
        try:
            column_values[12] = int(values[12].strip()) + int(values[13].strip())
        except ValueError:
            # the first line was the headers, get another
            return False
        #  starttime
        try:
            temp_start_in = datetime.strptime(values[6].strip(), '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            # There is no data             
            temp_start_in = float("inf")   
        try:
            temp_start_out = datetime.strptime(values[7].strip(), '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            # There is no data             
            temp_start_out = float("inf")  
        # Which one did started first?    
        column_values[0] = values[6].strip() if temp_start_in < temp_start_out else values[7].strip()
        first_flow_time = temp_start_in if temp_start_in < temp_start_out else temp_start_out
        
        # Duration (first end time)
        try:
            temp_stop_in = datetime.strptime(values[8].strip(), '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            # There is no data             
            temp_stop_in = float("-inf")   
        try:
            temp_stop_out = datetime.strptime(values[9].strip(), '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            # There is no data             
            temp_stop_out = float("-inf")  
        # Which one did stop first?    
        last_flow_time = temp_stop_in if temp_stop_in > temp_stop_out else temp_stop_out
        # Finally the duration         
        diff = last_flow_time - first_flow_time
        column_values[1] = diff.total_seconds()
        # proto
        column_values[2] = values[5].strip()
        # saddr
        column_values[3] = values[1].strip()
        # sport
        column_values[4] = values[3].strip()
        # daddr
        column_values[6] = values[2].strip()
        # dport
        column_values[7] = values[4].strip()
        # state
        column_values[8] = ""
        # stos
        column_values[9] = 0
        # dtos
        column_values[10] = 0
        # pkts (no amount of pkts info int he other dataset
        column_values[11] = -1
        return column_values

    def run(self):
        try:
            while True:
                if not self.queue.empty():
                    line = self.queue.get()
                    if 'stop' != line:
                        # Process this flow
                        #nline = ','.join(line.strip().split(',')[:13])
                        nline = ','.join(line.strip().split(',')[:17])
                        try:
                            #column_values = nline.split(',')
                            column_values = self.convert(nline.split(','))
                            if not column_values:
                                continue
                            if self.slot_starttime == -1:
                                # First flow
                                try:
                                    #self.slot_starttime = datetime.strptime(column_values[0], '%Y/%m/%d %H:%M:%S.%f')
                                    self.slot_starttime = datetime.strptime(column_values[0], '%Y-%m-%d %H:%M:%S.%f')
                                except ValueError:
                                    continue
                                self.slot_endtime = self.slot_starttime + self.slot_width
                            #flowtime = datetime.strptime(column_values[0], '%Y/%m/%d %H:%M:%S.%f')
                            flowtime = datetime.strptime(column_values[0], '%Y-%m-%d %H:%M:%S.%f')
                            if flowtime >= self.slot_starttime and flowtime < self.slot_endtime:
                                # Inside the slot
                                tuple4 = column_values[3]+'-'+column_values[6]+'-'+column_values[7]+'-'+column_values[2]
                                srcip = False
                                if self.anonymize:
                                    # Hash the IP 
                                    srcip = tuple4.split('-')[0]
                                    dstip = tuple4.split('-')[1]
                                    dstport = tuple4.split('-')[2]
                                    proto = tuple4.split('-')[3]
                                    t_hashed_ip = hashlib.md5()
                                    t_hashed_ip.update(srcip)
                                    hash_src_ip = t_hashed_ip.hexdigest()
                                    tuple4 = hash_src_ip + '-' + dstip + '-' + dstport + '-' + proto
                                # Get the tuple, but store the original src ip if we create a new tuple
                                tuple = self.get_tuple(tuple4, orig_src_ip=srcip)
                                if self.verbose:
                                    if len(tuple.state) == 0:
                                        tuple.set_color(red)
                                tuple.add_new_flow(column_values)
                                # Detection
                                self.detect(tuple)
                            elif flowtime > self.slot_endtime:
                                # Out of time slot
                                self.process_out_of_time_slot(column_values)
                        except UnboundLocalError:
                            print 'Probable empty file.'
                    else:
                        # Empty queue
                        try:
                            # Process the last flows in the last time slot
                            self.process_out_of_time_slot(column_values)
                            if self.anonymize:
                                # Open the file for storing the anonymized src ip addresses
                                (fd, anon_matching_file_path) = tempfile.mkstemp(suffix='-stratosphere-anonips.txt', dir='.', text=True)
                                anon_matching_file = open(anon_matching_file_path, 'w+')
                                anon_matching_file.write('HashedIP' + ',' + 'OriginalIP' + '\n')
                                # The same src ip can be in different tuples, so temporary store them so we don't repeat them
                                temp_src_ips = {}
                                for tup in self.tuples:
                                    try:
                                        isthere = temp_src_ips[self.tuples[tup].get_original_src_ip()]
                                    except KeyError:
                                        # Is new, so print it
                                        anon_matching_file.write(self.tuples[tup].get_src_ip() + ',' + self.tuples[tup].get_original_src_ip() + '\n')
                                        anon_matching_file.flush()
                                        temp_src_ips[self.tuples[tup].get_original_src_ip()] = ''
                                print 'Created output file with anonymized IP list. {}'.format(anon_matching_file_path)
                                anon_matching_file.close()
                                os.close(fd)
                        except UnboundLocalError:
                            print 'Probable empty file.'
                            # Here for some reason we still miss the last flow. But since is just one i will let it go for now.
                        # Just Return
                        return True

        except KeyboardInterrupt:
            return True
            if self.anonymize:
                self.anon_matching_file.close()
        except Exception as inst:
            print '\tProblem with Processor()'
            print type(inst)     # the exception instance
            print inst.args      # arguments stored in .args
            print inst           # __str__ allows args to printed directly
            sys.exit(1)






####################
# Main
####################
print 'Stratosphere Linux IPS. Version {}\n'.format(version)

# Parse the parameters
parser = argparse.ArgumentParser()
parser.add_argument('-a', '--amount', help='Minimum amount of flows that should be in a tuple to be printed.', action='store', required=False, type=int, default=-1)
parser.add_argument('-v', '--verbose', help='Amount of verbosity.', action='store', default=1, required=False, type=int)
parser.add_argument('-p', '--print_detections', help='Only print the tuples that are detected.', action='store_true', default=False, required=False)
parser.add_argument('-w', '--width', help='Width of the time slot used for the analysis. In minutes.', action='store', default=1, required=False, type=int)
parser.add_argument('-s', '--sound', help='Play a small sound when a periodic connections is found.', action='store_true', default=False, required=False)
parser.add_argument('-d', '--datawhois', help='Get and show the whois info for the destination IP in each tuple', action='store_true', default=False, required=False)
parser.add_argument('-D', '--dontdetect', help='Dont detect the malicious behavior in the flows. Just print the connections.', default=False, action='store_true', required=False)
parser.add_argument('-f', '--folder', help='Folder with models to apply for detection.', action='store', required=False)
parser.add_argument('-A', '--anonymize', help='Anonymize the source IP addresses before priting them.', action='store_true', default=False, required=False)
args = parser.parse_args()

# Global shit for whois cache. The tuple needs to access it but should be shared, so global
whois_cache = {}

# Do we need sound?
if args.sound:
    import pygame.mixer
    pygame.mixer.init(44100)
    pygame.mixer.music.load('periodic.ogg')

# Do we need the hashing libs?
if args.anonymize:
    import hashlib
    import tempfile

# Set the folder with models if specified
if args.folder and not __markov_models__.set_models_folder(args.folder):
    sys.exit(-1)

# Create the queue
queue = Queue()
# Create the thread and start it
processorThread = Processor(queue, timedelta(minutes=args.width), 'True' if args.folder else 'False', args.datawhois, args.verbose, args.amount, args.dontdetect, args.anonymize)
processorThread.start()

# Just put the lines in the queue as fast as possible
for line in sys.stdin:
    queue.put(line)
    #print 'A: {}'.format(queue.qsize())
print 'Finished Processing the input.'
# Shall we wait? Not sure. Seems that not
time.sleep(1)
queue.put('stop')
