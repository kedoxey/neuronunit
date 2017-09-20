##
# Assumption that this file was executed after first executing the bash: ipcluster start -n 8 --profile=default &
##

import matplotlib # Its not that this file is responsible for doing plotting, but it calls many modules that are, such that it needs to pre-empt
# setting of an appropriate backend.
matplotlib.use('agg')
import os
os.system('')
import quantities as pq
from numpy import random

#from dask.distributed import Client
#client = Client('scheduler-address:8786')
'''
http://distributed.readthedocs.io/en/latest/queues.html
And we set up an input Queue and map our functions across it.

>>> from queue import Queue
>>> input_q = Queue()
>>> remote_q = client.scatter(input_q)
>>> inc_q = client.map(inc, remote_q)
>>> double_q = client.map(double, inc_q)
We will fill the input_q with local data from some stream, and then remote_q, inc_q and double_q will fill with Future objects as data gets moved around.

We gather the futures from the double_q back to a queue holding local data in the local process.
'''

from numba import autojit#, prange
@autojit
def parallel_sum(A):
    sum = 0.0
    for i in prange(A.shape[0]):
        sum += A[i]

    return sum


import sys
import ipyparallel as ipp
from ipyparallel import Client
c = Client()  # connect to IPyParallel cluster
e = c.become_dask()  # start dask on top of IPyParallel
#print(e)

from ipyparallel import depend, require, dependent

import get_neab
rc = ipp.Client(profile='default')
THIS_DIR = os.path.dirname(os.path.realpath('nsga_parallel.py'))
this_nu = os.path.join(THIS_DIR,'../../')
sys.path.insert(0,this_nu)
from neuronunit import tests
#from deap import hypervolume
import deap
# hypervolume is in master
# not dev.
#from deap.benchmarks.tools import diversity, convergence, hypervolume
rc[:].use_cloudpickle()
dview = rc[:]




class Individual(object):
    '''
    When instanced the object from this class is used as one unit of chromosome or allele by DEAP.
    Extends list via polymorphism.
    '''
    def __init__(self, *args):
        list.__init__(self, *args)
        self.error=None
        self.results=None
        self.name=''
        self.attrs = {}
        self.params=None
        self.score=None
        self.fitness=None
        self.lookup={}
        self.rheobase=None
        self.fitness = creator.FitnessMin

@require('numpy, model_parameters, deap','random')
def import_list():
    Individual = ipp.Reference('Individual')
    from deap import base, creator, tools
    import deap
    import random
    history = deap.tools.History()
    toolbox = base.Toolbox()
    import model_parameters as modelp
    import numpy as np
    sub_set = []
    whole_BOUND_LOW = [ np.min(i) for i in modelp.model_params.values() ]
    whole_BOUND_UP = [ np.max(i) for i in modelp.model_params.values() ]
    BOUND_LOW = whole_BOUND_LOW
    BOUND_UP = whole_BOUND_UP
    NDIM = len(BOUND_UP)#+1
    def uniform(low, up, size=None):
        try:
            return [random.uniform(a, b) for a, b in zip(low, up)]
        except TypeError:
            return [random.uniform(a, b) for a, b in zip([low] * size, [up] * size)]
    # weights vector should compliment a numpy matrix of eigenvalues and other values
    creator.create("FitnessMin", base.Fitness, weights=(-1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0))
    creator.create("Individual", list, fitness=creator.FitnessMin)
    toolbox.register("attr_float", uniform, BOUND_LOW, BOUND_UP, NDIM)
    toolbox.register("individual", tools.initIterate, creator.Individual, toolbox.attr_float)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)
    toolbox.register("select", tools.selNSGA2)
    toolbox.register("mate", tools.cxSimulatedBinaryBounded, low=BOUND_LOW, up=BOUND_UP, eta=30.0)
    toolbox.register("mutate", tools.mutPolynomialBounded, low=BOUND_LOW, up=BOUND_UP, eta=20.0, indpb=1.0/NDIM)
    return toolbox, tools, history, creator, base
(toolbox, tools, history, creator, base) = import_list()
dview.push({'Individual':Individual})
dview.apply_sync(import_list)

def get_trans_dict(param_dict):
    trans_dict = {}
    for i,k in enumerate(list(param_dict.keys())):
        trans_dict[i]=k
    return trans_dict
import model_parameters
param_dict = model_parameters.model_params

def dt_to_ind(dtc,td):
    '''
    Re instanting data transport container at every update dtcpop
    is Noneifying its score attribute, and possibly causing a
    performance bottle neck.
    '''
    ind =[]
    for k in td.keys():
        ind.append(dtc.attrs[td[k]])
    ind.append(dtc.rheobase)
    return ind

@require('numpy as np', 'copy','evaluate_as_module')
def update_dtc_pop(pop, trans_dict):
    '''
    inputs a population of genes/alleles, the population size MU, and an optional argument of a rheobase value guess
    outputs a population of genes/alleles, a population of individual object shells, ie a pickleable container for gene attributes.
    Rationale, not every gene value will result in a model for which rheobase is found, in which case that gene is discarded, however to
    compensate for losses in gene population size, more gene samples must be tested for a successful return from a rheobase search.
    If the tests return are successful these new sampled individuals are appended to the population, and then their attributes are mapped onto
    corresponding virtual model objects.
    '''
    import copy
    import numpy as np
    pop = [toolbox.clone(i) for i in pop ]
    import evaluate_as_module

    def transform(ind):
        dtc = evaluate_as_module.DataTC()
        param_dict = {}
        for i,j in enumerate(ind):
            param_dict[trans_dict[i]] = str(j)
        dtc.attrs = param_dict
        dtc.evaluated = False
        return dtc


    if len(pop) > 0:
        dtcpop = dview.map_sync(transform, pop)
        dtcpop = list(copy.copy(dtcpop))
    else:
        # In this case pop is not really a population but an individual
        # but parsimony of naming variables
        # suggests not to change the variable name to reflect this.
        dtcpop = transform(pop)
    return dtcpop



def check_rheobase(dtcpop,pop=None):
    '''
    inputs a population of genes/alleles, the population size MU, and an optional argument of a rheobase value guess
    outputs a population of genes/alleles, a population of individual object shells, ie a pickleable container for gene attributes.
    Rationale, not every gene value will result in a model for which rheobase is found, in which case that gene is discarded, however to
    compensate for losses in gene population size, more gene samples must be tested for a successful return from a rheobase search.
    If the tests return are successful these new sampled individuals are appended to the population, and then their attributes are mapped onto
    corresponding virtual model objects.
    '''
    def check_fix_range(dtc):
        '''
        Inputs: lookup, A dictionary of previous current injection values
        used to search rheobase
        Outputs: A boolean to indicate if the correct rheobase current was found
        and a dictionary containing the range of values used.
        If rheobase was actually found then rather returning a boolean and a dictionary,
        instead logical True, and the rheobase current is returned.
        given a dictionary of rheobase search values, use that
        dictionary as input for a subsequent search.
        '''
        import pdb
        import copy
        import numpy as np
        import quantities as pq
        sub=[]
        supra=[]
        steps=[]
        dtc.rheobase = 0.0
        for k,v in dtc.lookup.items():
            dtc.searchedd[v]=float(k)

            if v == 1:
                #A logical flag is returned to indicate that rheobase was found.
                dtc.rheobase=float(k)
                dtc.searched.append(float(k))
                dtc.steps = 0.0
                dtc.boolean = True
                return dtc
            elif v == 0:
                sub.append(k)
            elif v > 0:
                supra.append(k)

        sub = np.array(sub)
        supra = np.array(supra)

        if len(sub)!=0 and len(supra)!=0:
            #this assertion would only be occur if there was a bug
            assert sub.max()<=supra.min()
        if len(sub) and len(supra):
            center = list(np.linspace(sub.max(),supra.min(),9.0))
            center = [ i for i in center if not i == sub.max() ]
            center = [ i for i in center if not i == supra.min() ]
            center[int(len(center)/2)+1]=(sub.max()+supra.min())/2.0
            steps = [ i*pq.pA for i in center ]

        elif len(sub):
            steps = list(np.linspace(sub.max(),2*sub.max(),9.0))
            steps = [ i for i in steps if not i == sub.max() ]
            steps = [ i*pq.pA for i in steps ]

        elif len(supra):
            step = list(np.linspace(-2*(supra.min()),supra.min(),9.0))
            steps = [ i for i in steps if not i == supra.min() ]
            steps = [ i*pq.pA for i in steps ]

        dtc.steps = steps
        dtc.rheobase = None
        return copy.copy(dtc)

    @require('quantities', 'get_neab', 'neuronunit')
    def check_current(ampl,dtc):
        '''
        Inputs are an amplitude to test and a virtual model
        output is an virtual model with an updated dictionary.
        '''

        #global model
        import quantities as pq
        import get_neab
        from neuronunit.models import backends
        from neuronunit.models.reduced import ReducedModel

        #new_file_path = str(get_neab.LEMS_MODEL_PATH)+str(int(os.getpid()))
        model = ReducedModel(get_neab.LEMS_MODEL_PATH,name=str('vanilla'),backend='NEURON')
        model.load_model()
        model.set_attrs(**dtc.attrs)
        #model.update_run_params(dtc.attrs)

        DELAY = 100.0*pq.ms
        DURATION = 1000.0*pq.ms
        params = {'injected_square_current':
                  {'amplitude':100.0*pq.pA, 'delay':DELAY, 'duration':DURATION}}


        if float(ampl) not in dtc.lookup or len(dtc.lookup)==0:

            current = params.copy()['injected_square_current']

            uc = {'amplitude':ampl}
            current.update(uc)
            current = {'injected_square_current':current}
            dtc.run_number += 1
            model.set_attrs(** dtc.attrs)
            model.name = dtc.attrs
            #model.update_run_params(dtc.attrs)
            #model.update_run_params(dtc.attrs)
            model.inject_square_current(current)
            dtc.previous = ampl
            n_spikes = model.get_spike_count()
            dtc.lookup[float(ampl)] = n_spikes
            if n_spikes == 1:
                dtc.rheobase = float(ampl)

                dtc.name = str('rheobase {0} parameters {1}'.format(str(current),str(model.params)))
                dtc.boolean = True
                return dtc

            return dtc
        if float(ampl) in dtc.lookup:
            return dtc

    #from itertools import repeat
    import numpy as np
    import copy
    import pdb
    import get_neab

    @require('itertools','numpy','copy','pdb','get_neab')
    def init_dtc(dtc):
        if dtc.initiated == True:
            # expand values in the range to accomodate for mutation.
            # but otherwise exploit memory of this range.

            if type(dtc.steps) is type(float):
                dtc.steps = [ 0.75 * dtc.steps, 1.25 * dtc.steps ]
            elif type(dtc.steps) is type(list):
                dtc.steps = [ s * 1.25 for s in dtc.steps ]
            #assert len(dtc.steps) > 1
            dtc.initiated = True # logically unnecessary but included for readibility

        if dtc.initiated == False:
            import quantities as pq
            import numpy as np
            dtc.boolean = False
            steps = np.linspace(0,250,7.0)
            steps_current = [ i*pq.pA for i in steps ]
            dtc.steps = steps_current
            dtc.initiated = True
        return dtc
    @require('neuronunit','get_neab','itertools')
    def find_rheobase(dtc):
        from neuronunit.models import backends
        from neuronunit.models.reduced import ReducedModel
        import get_neab
        #print(pid_map[int(os.getpid())])

        #new_file_path = str(get_neab.LEMS_MODEL_PATH)+str(os.getpid())
        model = ReducedModel(get_neab.LEMS_MODEL_PATH,name=str('vanilla'),backend='NEURON')
        model.load_model()
        model.set_attrs(**dtc.attrs)
        #model.update_run_params(dtc.attrs)
        cnt = 0
        # If this it not the first pass/ first generation
        # then assume the rheobase value found before mutation still holds until proven otherwise.
        if type(dtc.rheobase) is not type(None):
            dtc = check_current(dtc.rheobase,dtc)
        # If its not true enter a search, with ranges informed by memory
        cnt = 0
        #from itertools import repeat
        while dtc.boolean == False:
            dtc.searched.append(dtc.steps)
            # These three lines are a memory killer.
            #dtcpop = dview.map_sync(check_current,dtc.steps,repeat(dtc))
            #for dtc in dtcpop:
            #    dtc.lookup.extend(dtc.lookup)
            for step in dtc.steps:
                dtc = check_current(step, dtc)
                dtc = check_fix_range(dtc)
            cnt += 1
        return dtc

    ## initialize where necessary.
    #import time
    dtcpop = list(dview.map_sync(init_dtc,dtcpop))

    # if a population has already been evaluated it may be faster to let it
    # keep its previous rheobase searching range where this
    # memory of a previous range as acts as a guess as the next mutations range.
    #dtcpop1 = []
    #for v in dtcpop:
        #dtcpop1.append(find_rheobase(v))
    #dtcpop = dtcpop1  #list(map(find_rheobase,dtcpop))
    dtcpop = list(dview.map_sync(find_rheobase,dtcpop))

    return dtcpop, pop




##
# Start of the Genetic Algorithm
# For good results, NGEN * MU  the number of generations
# time the size of the gene pool
# should at least be as big as number of dimensions/model parameters
# explored.
##

def check_current(ampl,dtc):
    '''
    Inputs are an amplitude to test and a virtual model
    output is an virtual model with an updated dictionary.
    '''

    #global model
    import quantities as pq
    import get_neab
    from neuronunit.models import backends
    from neuronunit.models.reduced import ReducedModel

    #new_file_path = str(get_neab.LEMS_MODEL_PATH)+str(int(os.getpid()))
    model = ReducedModel(get_neab.LEMS_MODEL_PATH,name=str('vanilla'),backend='NEURON')
    model.load_model()
    model.set_attrs(**dtc.attrs)
    #model.update_run_params(dtc.attrs)

    DELAY = 100.0*pq.ms
    DURATION = 1000.0*pq.ms
    params = {'injected_square_current':
              {'amplitude':100.0*pq.pA, 'delay':DELAY, 'duration':DURATION}}


    if float(ampl) not in dtc.lookup or len(dtc.lookup)==0:

        current = params.copy()['injected_square_current']

        uc = {'amplitude':ampl}
        current.update(uc)
        current = {'injected_square_current':current}
        dtc.run_number += 1
        model.set_attrs(** dtc.attrs)
        model.name = dtc.attrs
        #model.update_run_params(dtc.attrs)
        #model.update_run_params(dtc.attrs)
        model.inject_square_current(current)
        dtc.previous = ampl
        n_spikes = model.get_spike_count()
        print(n_spikes,dtc.rheobase,ampl,dtc.attrs)
        dtc.lookup[float(ampl)] = n_spikes
        if n_spikes == 1:
            dtc.rheobase = float(ampl)

            dtc.name = str('rheobase {0} parameters {1}'.format(str(current),str(model.params)))
            dtc.boolean = True
            return dtc

        return dtc
    if float(ampl) in dtc.lookup:
        return dtc


MU = 4
NGEN = 2
CXPB = 0.9

import numpy as np
pf = tools.ParetoFront()

stats = tools.Statistics(lambda ind: ind.fitness.values)
stats.register("min", np.min, axis=0)
stats.register("max", np.max, axis=0)
stats.register("avg", np.mean)
stats.register("std", np.std)

logbook = tools.Logbook()
logbook.header = "gen", "evals", "min", "max", "avg", "std"

dview.push({'pf':pf})
trans_dict = get_trans_dict(param_dict)
td = trans_dict
dview.push({'trans_dict':trans_dict,'td':td})

pop = toolbox.population(n = MU)
pop = [ toolbox.clone(i) for i in pop ]
dview.scatter('Individual',pop)



def check_paths():
    '''
    import paths and test for consistency
    '''
    import neuronunit
    from neuronunit.models.reduced import ReducedModel
    import get_neab
    model = ReducedModel(get_neab.LEMS_MODEL_PATH,name='vanilla',backend='NEURON')
    model.load_model()
    return neuronunit.models.__file__

path_serial = check_paths()
paths_parallel = dview.apply_async(check_paths).get_dict()
assert path_serial == paths_parallel[0]

dtcpop = update_dtc_pop(pop, td)
print(dtcpop)
dtcpop , _ = check_rheobase(dtcpop)
for ind in dtcpop:
    print(ind.rheobase)

rh_values_unevolved = [v.rheobase for v in dtcpop ]
new_checkpoint_path = str('un_evolved')+str('.p')
import pickle
with open(new_checkpoint_path,'wb') as handle:#
    pickle.dump([dtcpop,rh_values_unevolved], handle)


# sometimes done in serial in order to get access to opaque stdout/stderr

#fitnesses = []
#for v in dtcpop:
#   fitnesses.append(evaluate_as_module.evaluate(v))
   #pdb.set_trace()
import copy
import evaluate_as_module
#dtcpop = dview.map_sync(evaluate_as_module.pre_evaluate, copy.copy(dtcpop))
#from itertools import repeat
dtcpop = [ v for v in dtcpop if v.rheobase > 0.0 ]
for d in dtcpop:
    print('testing dubious rheobase values \n\n\n')
    dtc = check_current(d.rheobase, d)
#dtcpop = list(dview.map_sync(evaluate_as_module.pre_evaluate,copy.copy(dtcpop)))
fitnesses = list(dview.map_sync(evaluate_as_module.evaluate, copy.copy(dtcpop)))

#fitnesses = dview.map(evaluate_as_module.evaluate, copy.copy(producer)).get()




'''
Eventually want to use RAMBackend to save time.
from neuronunit.models import backends
from neuronunit.models.reduced import ReducedModel
new_file_path = str(get_neab.LEMS_MODEL_PATH)+str(os.getpid())
model = ReducedModel(new_file_path,name=str('vanilla'),backend='DiskBackend')
model.load_model()
model.update_run_params(dtc.attrs)
'''

#fitnesses = dview.map_sync(evaluate, copy.copy(dtcpop))
for ind, fit in zip(pop, fitnesses):
    ind.fitness.values = fit


pop = tools.selNSGA2(pop, MU)

# only update the history after crowding distance has been assigned
deap.tools.History().update(pop)


### After an evaluation of error its appropriate to display error statistics
#pf = tools.ParetoFront()
pf.update([toolbox.clone(i) for i in pop])
#hvolumes = []
#hvolumes.append(hypervolume(pf))

record = stats.compile(pop)
logbook.record(gen=0, evals=len(pop), **record)
print(logbook.stream)

def rh_difference(unit_predictions):
    unit_observations = get_neab.tests[0].observation['value']
    to_r_s = unit_observations.units
    unit_predictions = unit_predictions.rescale(to_r_s)
    unit_delta = np.abs( np.abs(unit_observations)-np.abs(unit_predictions) )
    print(unit_delta)
    return float(unit_delta)

verbose = True
means = np.array(logbook.select('avg'))
gen = 1
rh_mean_status = np.mean([ v.rheobase for v in dtcpop ])
rhdiff = rh_difference(rh_mean_status * pq.pA)
print(rhdiff)
verbose = True
while (gen < NGEN and means[-1] > 0.05):
    # Although the hypervolume is not actually used here, it can be used
    # As a terminating condition.
    # hvolumes.append(hypervolume(pf))
    gen += 1
    print(gen)
    offspring = tools.selNSGA2(pop, len(pop))
    if verbose:
        for ind in offspring:
            print('what do the weights without values look like? {0}'.format(ind.fitness.weights[:]))
            print('what do the weighted values look like? {0}'.format(ind.fitness.wvalues[:]))
            #print('has this individual been evaluated yet? {0}'.format(ind.fitness.valid[0]))
            print(rhdiff)
    offspring = [toolbox.clone(ind) for ind in offspring]

    for ind1, ind2 in zip(offspring[::2], offspring[1::2]):
        if random.random() <= CXPB:
            toolbox.mate(ind1, ind2)
        toolbox.mutate(ind1)
        toolbox.mutate(ind2)
        # deleting the fitness values is what renders them invalid.
        # The invalidness is used as a flag for recalculating them.
        # Their fitneess needs deleting since the attributes which generated these values have been mutated
        # and hence they need recalculating
        # Mutation also implies breeding, if a gene is mutated it was also recently recombined.
        del ind1.fitness.values, ind2.fitness.values

    invalid_ind = []
    for ind in offspring:
        if ind.fitness.valid == False:
            invalid_ind.append(ind)
    # Need to make sure that _pop does not replace instances of the same model
    # Thus waisting computation.
    dtcoffspring = update_dtc_pop(copy.copy(invalid_ind), trans_dict) #(copy.copy(invalid_ind), td)
    #import evaluate_as_module as em
    #dtcpop , _ = check_rheobase(dtcpop)
    dtcoffspring , _ =  check_rheobase(copy.copy(dtcoffspring))
    rh_mean_status = np.mean([ v.rheobase for v in dtcoffspring ])
    rhdiff = rh_difference(rh_mean_status * pq.pA)
    print('the difference: {0}'.format(rh_difference(rh_mean_status * pq.pA)))
    # sometimes fitness is assigned in serial, although slow gives access to otherwise hidden
    # stderr/stdout
    # fitnesses = []
    # for v in dtcoffspring:
    #    fitness.append(evaluate(v))
    #import evaluate_as_module
    dtcpop = [ v for v in dtcpop if v.rheobase > 0.0 ]
    for d in dtcpop:
        print('testing dubious rheobase values \n\n\n')
        d = check_current(d.rheobase, d)
    fitnesses = list(dview.map_sync(evaluate_as_module.evaluate, copy.copy(dtcoffspring)))
    #fitnesses = list(dview.map_sync(evaluate, copy.copy(dtcoffspring)))

    mf = np.mean(fitnesses)

    for ind, fit in zip(copy.copy(invalid_ind), fitnesses):
        ind.fitness.values = fit
        if verbose:
            print('what do the weights without values look like? {0}'.format(ind.fitness.weights))
            print('what do the weighted values look like? {0}'.format(ind.fitness.wvalues))
            print('has this individual been evaluated yet? {0}'.format(ind.fitness.valid))

    # Its possible that the offspring are worse than the parents of the penultimate generation
    # Its very likely for an offspring population to be less fit than their parents when the pop size
    # is less than the number of parameters explored. However this effect should stabelize after a
    # few generations, after which the population will have explored and learned significant error gradients.
    # Selecting from a gene pool of offspring and parents accomodates for that possibility.
    # There are two selection stages as per the NSGA example.
    # https://github.com/DEAP/deap/blob/master/examples/ga/nsga2.py
    # pop = toolbox.select(pop + offspring, MU)

    # keys = history.genealogy_tree.keys()
    # Optionally
    # Grab evaluated history its and chuck them into the mixture.
    # This may cause stagnation of evolution however.
    # We want to select among the best from the whole history of the GA, not just penultimate and present generations.
    # all_hist = [ history.genealogy_history[i] for i in keys if history.genealogy_history[i].fitness.valid == True ]
    # pop = tools.selNSGA2(offspring + all_hist, MU)

    pop = tools.selNSGA2(offspring + pop, MU)

    record = stats.compile(pop)
    history.update(pop)

    logbook.record(gen=gen, evals=len(pop), **record)
    pf.update([toolbox.clone(i) for i in pop])
    means = np.array(logbook.select('avg'))
    pf_mean = np.mean([ i.fitness.values for i in pf ])


    # if the means are not decreasing at least as an overall trend something is wrong.
    print('means from logbook: {0} from manual meaning the fitness: {1}'.format(means,mf))
    print('means: {0} pareto_front first: {1} pf_mean {2}'.format(logbook.select('avg'), \
                                                        np.sum(np.mean(pf[0].fitness.values)),\
                                                        pf_mean))
os.system('conda install graphviz plotly cufflinks')
from neuronunit import plottools
plottools.surfaces(history,td)
best, worst = plottools.best_worst(history)
listss = [best , worst]
best_worst = update_dtc_pop(listss,td)
#import evaluate_as_module as em

best_worst , _ = check_rheobase(best_worst)
rheobase_values = [v.rheobase for v in dtcoffspring ]
dtchistory = update_dtc_pop(history.genealogy_history.values(),td)

import pickle
with open('complete_dump.p','wb') as handle:
   pickle.dump([pf,dtcoffspring,history,logbook,rheobase_values,best_worst,dtchistory,hvolumes],handle)

lists = pickle.load(open('complete_dump.p','rb'))
#dtcoffspring2,history2,logbook2 = lists[0],lists[1],lists[2]
plottools.surfaces(history,td)
import plottools
#reload(plottools)
#dtchistory = _pop(history.genealogy_history.values(),td)
#best, worst = plottools.best_worst(history)
#listss = [best , worst]
#best_worst = _pop(listss,td)
#best_worst , _ = check_rheobase(best_worst)
best = dtc
unev = pickle.load(open('un_evolved.p','rb'))
unev, rh_values_unevolved = unev[0], unev[1]
for x,y in enumerate(unev):
    y.rheobase = rh_values_unevolved[x]
dtcoffpsring.append(unev)
plottools.shadow(dtcoffspring,best_worst[0])
plottools.plotly_graph(history,dtchistory)
#plottools.graph_s(history)
plottools.plot_log(logbook)
plottools.not_just_mean(hvolumes,logbook)
plottools.plot_objectives_history(logbook)

#Although the pareto front surely contains the best candidate it cannot contain the worst, only history can.
#best_ind_dict_dtc = _pop(pf[0:2],td)
#best_ind_dict_dtc , _ = check_rheobase(best_ind_dict_dtc)



print(best_worst[0].attrs,' == ', best_ind_dict_dtc[0].attrs, ' ? should be the same (eyeball)')
print(best_worst[0].fitness.values,' == ', best_ind_dict_dtc[0].fitness.values, ' ? should be the same (eyeball)')

# This operation converts the population of virtual models back to DEAP individuals
# Except that there is now an added 11th dimension for rheobase.
# This is not done in the general GA algorithm, since adding an extra dimensionality that the GA
# doesn't utilize causes a DEAP error, which is reasonable.

plottools.bar_chart(best_worst[0])
plottools.pca(final_population,dtcpop,fitnesses,td)
#test_dic = bar_chart(best_worst[0])
plottools.plot_evaluate( best_worst[0],best_worst[1])
#plottools.plot_db(best_worst[0],name='best')
#plottools.plot_db(best_worst[1],name='worst')

plottools.plot_evaluate( best_worst[0],best_worst[1])
plottools.plot_db(best_worst[0],name='best')
plottools.plot_db(best_worst[1],name='worst')
