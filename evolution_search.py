from gepcore.utils import convolution, cell_graph
from gepcore.entity import Gene, Chromosome
from gepcore.symbol import PrimitiveSet
from gepcore.operators import *
from gepnet.model_v2 import get_gepnet, arch_config
from gepnet.utils import count_parameters
from scipy.special import expit
from fastai.vision import *
#from fastai.utils.mod_display import *
import argparse

# import evolutionary tools from DEAP and GEPPY
from deap import creator, base, tools
from geppy import Toolbox, gep_simple

parser = argparse.ArgumentParser(description='evolutionary architectural search')
# evolutionary algorithm hyperparameter
parser.add_argument('--head_length', type=int, default=3, help='length of gene head')
parser.add_argument('--num_genes', type=int, default=2, help='num of genes per chromosome')
parser.add_argument('--num_gen', type=int, default=20, help='num of generations')
parser.add_argument('--pop_size', type=int, default=20, help='size of population')
parser.add_argument('--cx_pb', type=list, default=[0.1, 0.6], help='crossover probability')
parser.add_argument('--mu_pb', type=float, default=0.044, help='uniform mutation probability')
parser.add_argument('--invert_pb', type=float, default=0.1, help='inversion probability')
parser.add_argument('--transpose_pb', type=float, default=0.1, help='transposition probability')
parser.add_argument('--elites', type=int, default=1, help='num of elites selected')
parser.add_argument('--hof', type=int, default=2, help='hall of fame (record best individuals)')
parser.add_argument('--path', type=str, default='comp_graphs/experiment_4', help='path to save individuals')

# architecture config
parser.add_argument('--depth_coeff', type=float, default=1.0, help='layer scalar')
parser.add_argument('--width_coeff', type=float, default=1.0, help='channel scalar')
parser.add_argument('--channels', type=int, default=16, help='initial out channels')
parser.add_argument('--repeat_list', type=list, default=[1, 1, 1], help='cells repetitions list')
parser.add_argument('--classes', type=int, default=10, help='num of labels')

# training search architecture
parser.add_argument('--seed', type=int, default=200, help='training seed')
parser.add_argument('--max_lr', type=float, default=1e-1, help='max learning rate')
parser.add_argument('--wd', type=float, default=4e-4, help='weight decay')
parser.add_argument('--epochs', type=int, default=15, help='training epochs')
parser.add_argument('--bs', type=int, default=128, help='batch size')
args = parser.parse_args()


# define primitive set
pset = PrimitiveSet('cnn')
# add cellular encoding program symbols
pset.add_program_symbol(cell_graph.end)
pset.add_program_symbol(cell_graph.seq)
pset.add_program_symbol(cell_graph.cpo)
pset.add_program_symbol(cell_graph.cpi)

# add convolutional operations symbols
conv_symbol = convolution.get_symbol()
pset.add_cell_symbol(conv_symbol.conv1x1)
pset.add_cell_symbol(conv_symbol.conv3x3)
#pset.add_cell_symbol(conv_symbol.dwconv3x3)
pset.add_cell_symbol(conv_symbol.conv1x3)
pset.add_cell_symbol(conv_symbol.conv3x1)
#pset.add_cell_symbol(conv_symbol.maxpool3x3)


def build_model(comp_graph):
    conf = arch_config(comp_graph=comp_graph,
                       depth_coeff=args.depth_coeff,
                       width_coeff=args.width_coeff,
                       channels=args.channels,
                       repeat_list=args.repeat_list,
                       classes=args.classes)
    return get_gepnet(conf)


def search_model():
    # define fitness and individual type
    creator.create('FitnessMax', base.Fitness, weights=(1,))
    creator.create('Individual', Chromosome, fitness=creator.FitnessMax)

    # create individuals (genotype space)
    toolbox = Toolbox()
    toolbox.register('gene', Gene, pset, args.head_length)
    toolbox.register('individual', creator.Individual, toolbox.gene, args.num_genes)
    toolbox.register('population', tools.initRepeat, list, toolbox.individual)

    # translate individuals into computation graph (phenotype space)
    toolbox.register('comp_graph', cell_graph.generate_comp_graph)

    # evaluation function
    def evaluate(indv):
        _, comp_graph = toolbox.comp_graph(indv)
        net = build_model(comp_graph)
        acc = train_model(net)
        #size = count_parameters(net)
        fit = acc[1].item() #+ 1 / expit(size)
        return fit,

    # evaluate and select
    toolbox.register('evaluate', evaluate)
    toolbox.register('select', tools.selRoulette)

    # recombine and mutate
    #toolbox.register('cx_1p', cross_one_point, pb=args.cx_pb)
    toolbox.register('cx_gene', cross_gene, pb=args.cx_pb[0])
    toolbox.register('cx_2p', cross_two_point, pb=args.cx_pb[1])
    toolbox.register('mut_uniform', mutate_uniform, pset=pset, pb=args.mu_pb)
    toolbox.register('mut_invert_program', invert_program, pb=args.invert_pb)
    #toolbox.register('mut_invert_cell', invert_cell, pb=args.invert_pb)
    toolbox.register('mut_transpose_program', transpose_program, pb=args.transpose_pb)
    toolbox.register('mut_transpose_cell', transpose_cell, pb=args.transpose_pb)

    # evolution statistics
    stats = tools.Statistics(key=lambda ind: ind.fitness.values[0])
    stats.register("avg", np.mean)
    stats.register("std", np.std)
    stats.register("min", np.min)
    stats.register("max", np.max)

    # population size and best individual (hall of fame)
    pop = toolbox.population(n=args.pop_size)
    hof = tools.HallOfFame(args.hof)

    # call gep_simple evolutionary algorithm
    pop, log = gep_simple(pop,
                          toolbox,
                          n_generations=args.num_gen,
                          n_elites=args.elites,
                          stats=stats,
                          hall_of_fame=hof,
                          verbose=True)
    print('\n', log)

    # save and draw best individuals graphs
    for i, best in enumerate(hof):
        graph, _ = cell_graph.generate_comp_graph(best)
        cell_graph.save_graph(graph, args.path+'/best/indv_{}'.format(i))
        cell_graph.draw_graph(graph, args.path+'/best/indv_{}'.format(i))

    # save population graphs
    for i, p in enumerate(pop):
        graph, _ = cell_graph.generate_comp_graph(p)
        cell_graph.save_graph(graph, args.path+'/pop/indv_{}'.format(i))

    # save stats record
    with open(args.path+'/best/stats.pkl', 'wb') as f:
        pickle.dump(log, f,)


def train_model(net):
    if not torch.cuda.is_available():
        log.info('no gpu device available')
        sys.exit(1)

    # set random seeds for all individuals
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    # enable torch backends
    torch.backends.cudnn.enabled = True
    torch.backends.cudnn.benchmark = True

    path = untar_data(URLs.CIFAR)
    #tfms = get_transforms()
    data = (ImageList.from_folder(path/'train')
            .split_by_rand_pct(valid_pct=0.2, seed=args.seed)
            .label_from_folder()
            .databunch(bs=args.bs, num_workers=num_cpus())
            .normalize(cifar_stats))
            #.transform(tfms, size=32)

    learn = Learner(data, net, metrics=accuracy) #.to_fp16()
    learn.fit_one_cycle(args.epochs, args.max_lr, wd=args.wd)
    acc = learn.validate()
    return acc


def duration(sec):
    days, sec = sec//(24*3600), sec%(24*3600)
    hrs, sec = sec//(3600), sec%3600
    mins, sec = sec//60, sec%60
    print()
    print('Duration: %d:%02d:%02d:%02d' %(days, hrs, mins, sec))

# start evolution process
if __name__=='__main__':
    import time
    start = time.time()
    search_model()
    duration(time.time() - start)
