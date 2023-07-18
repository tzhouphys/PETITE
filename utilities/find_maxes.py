""" Generate samples of Standard Model EM shower events and save them.

    Uses saved VEGAS integrators to generate e+/- pair production and annihilation, 
    bremstrahlung and compton events for a range of initial particle energies 
    and target materials.
    The events are unweighted and saved for use in constructing a realistic shower.

    Typical usage:

    python Gen_Samples.py
"""
import os, sys
#path = os.getcwd()
#path = os.path.join(path,"../PETITE")
#sys.path.insert(0,path)

from PETITE.all_processes import *
import pickle
import copy
import numpy as np
import argparse
import random as rnd
from datetime import datetime
import vegas
from tqdm import tqdm

# Dictionary of proceses with corresponding x-secs, form factors and Q**2 functions
process_info ={    'PairProd' : {'diff_xsection': dsigma_pairprod_dimensionless,   'form_factor': g2_elastic, 'QSq_func': pair_production_q_sq_dimensionless},
                   'Comp'     : {'diff_xsection': dsigma_compton_dCT,     'form_factor': unity,      'QSq_func': dummy},
                    'Brem'     : {'diff_xsection': dsigma_brem_dimensionless,       'form_factor': g2_elastic, 'QSq_func': brem_q_sq_dimensionless},
                    'Ann'      : {'diff_xsection': dsigma_annihilation_dCT,'form_factor': unity,      'QSq_func': dummy},
                    'Moller'   : {'diff_xsection': dsigma_moller_dCT, 'form_factor': unity,      'QSq_func': dummy},
                    'Bhabha'   : {'diff_xsection': dsigma_bhabha_dCT, 'form_factor': unity,      'QSq_func': dummy}}

def get_file_names(path):
    ''' Get the names of all the files in a directory.
    Input:
        path: path to the directory
    Output:
        pickle_files: list of names of all the .p files in the directory (VEGAS integrator adaptive maps for given process and given energy)
        readme_file: name of the readme file in the directory (contains information about the process and the energy)
    '''
    all_files = os.listdir(path)
    # print('files:', all_files)
    pickle_files = [file for file in all_files if file.endswith(".p")]
    if 'readme.txt' in all_files:
        readme_file = 'readme.txt'
    else:
        readme_file = 0
    return(pickle_files, readme_file)

# do the find max work on an individual file
def do_find_max_work(params, process_file):
    """ Find the maximum value of the integrand for a given process_file.
    Input:
        params: dictionary of parameters for the process
        process_file: array of event_info and integrand which was read from a file (0.p, 1.p, ...)
    Output:
        samp_dict: dictionary of information about the sampling, containing:
            'neval': number of evaluations used in VEGAS (neval)
            'max_F': maximum value of the integrand (max_F)
            'Eg_min': minimum energy of the outgoing photon (Eg_min) if it was specified in the event_info
            'Ee_min': minimum energy of the outgoing electron (Ee_min) if it was specified in the event_info
            'adaptive_map': adaptive map used in the sampling (adaptive_map)
        xSec: dictionary of cross sections for each target material
        event_info['E_inc']: energy of the incoming particle
    """

    [diff_xsec, FF_func, QSq_func] = [params['diff_xsec'], params['FF_func'], params['QSq_func']]
    event_info, integrand_or_map = process_file
    if type(event_info) == np.float64: #FIXME: do we still need this?
        event_info = {'E_inc':event_info, 'process':params['process']}

    if type(integrand_or_map) == vegas._vegas.Integrator:
        integrand = integrand #FIXME: WTF?
        save_copy = copy.deepcopy(integrand.map)

    elif type(integrand_or_map) == vegas._vegas.AdaptiveMap:
        integrand = vegas.Integrator(map=integrand_or_map, nstrat=nstrat_options[params['process']])
        save_copy = copy.deepcopy(integrand_or_map)

    event_info_H = event_info
    event_info_H['Z_T'] = 1.0  #Take training information, make event_info for hydrogen target

    max_F = 0
    xSec = {}
    for ZT in params['Z_T']:
        xSec[ZT] = 0.0

    integrand.set(max_nhcube=1, neval=params['neval'])
    for trial_number in range(params['n_trials']):
        for x, wgt in integrand.random(): #scan over integrand
                
            #EvtInfo={'E_inc': E_inc, 'm_e': m_electron, 'Z_T': Z_H, 'alpha_FS': alpha_em, 'm_V': 0}
            MM_H = wgt*diff_xsec(event_info_H, x)
            if MM_H > max_F:
                max_F=MM_H

            form_factor_hydrogen = FF_func(event_info_H, QSq_func(x, event_info_H))

            # with nucleus as target
            for ZT in params['Z_T']:
                event_info_target = event_info
                event_info_target['Z_T'] = ZT #Take training information, make event_info for desired target
                form_factor_target = FF_func(event_info_target, QSq_func(x, event_info_target))
                xSec[ZT] += MM_H*form_factor_target/form_factor_hydrogen/params['n_trials']

    samp_dict_info = {"neval":params['neval'], "max_F": max_F, "adaptive_map": save_copy}
    if "Eg_min" in event_info.keys():
        samp_dict_info['Eg_min'] = event_info['Eg_min']
    if 'Ee_min' in event_info.keys():
        samp_dict_info['Ee_min'] = event_info['Ee_min']
    samp_dict = [event_info['E_inc'], samp_dict_info]
    #xSec_dict = [event_info['E_inc'], xSec]
    return(samp_dict, xSec, event_info['E_inc'])

def main(params):
    """ Find the maximum value of the integrand for a given process by looking into the directory containing the adaptive maps.
    Input:
        params: dictionary of parameters for the process containing the following keys:
            'process': list of processes to be run
            'Z_T': list of target materials to be run
            'neval': number of evaluations used in VEGAS
            'save_location': path to the mother directory whose subdirs contain the adaptive maps
            # add all needed parameters here!
    """
    '''
    Pseudoalgorithm:
    Loops over all processes in params['process']. 
    Access each 'process' directory containing the 'process_AdaptiveMaps.npy', and load these files.
    Runs do_find_max_work function on each of these files for each energy. 
    All the results are saved in a single file as a dictionary and pickled (sm_maps.pkl).
    *Later I will create the xsec dictionary and save it in a separate file (sm_xsec.pkl).
    '''

    # params['process'] should be a list of all processes to be run
    # available processes are ['PairProd', 'Comp', 'Ann', 'Brem', 'Moller', 'Bhabha']
    # If a single process is given, convert single process to a list if necessary
    if isinstance(params['process'], str):
        params['process'] = [params['process']]
    # Convert single target to a list if necessary
    if isinstance(params['Z_T'], int):
        params['Z_T'] = [params['Z_T']]
    print('List of processes: ', params['process'])
    print('List of atomic number of target materials: ', params['Z_T'])

    # Loop over all processes
    for process in params['process']:
        # Get the path to the directory containing the adaptive maps
        path = params['save_location'] + '/' + process + '/'
        # Get adaptive map main file (created by stitch_integrators)
        adaptive_maps_file = path + process + '_AdaptiveMaps.npy'
        # Load adaptive map file. Format: list of [params, adaptive_map]
        adaptive_maps = np.load(adaptive_maps_file, allow_pickle=True)
        # Initialise dictionaries to store samples and cross sections
        final_sampling_dict = {}
        final_xsec_dict = {}
        final_sampling_dict[process] = []
        final_xsec_dict[process] = {}
        # Initialise dictionary to store cross sections for each target material
        for ZT in params['Z_T']:
            final_xsec_dict[process][ZT] = []
        print('File being processed: ', adaptive_maps_file)
        # Add relevant info to params
        params['process']   = process
        params['diff_xsec'] = process_info[process]['diff_xsection']
        params['FF_func']   = process_info[process]['form_factor']
        params['QSq_func']  = process_info[process]['QSq_func']

        ####=====------ FIND MAX ------=====####
        # loop over all adaptive_map in adaptive_maps
        for adaptive_map in adaptive_maps:
            sampling, cross_section, incoming_energy = do_find_max_work(params, adaptive_map)
            # Append sampling dictionary to final sampling dictionary
            final_sampling_dict[process].append(sampling)
            # Append incoming energy and cross section dictionary to final cross section dictionary for each target material
            for ZT in params['Z_T']:
                final_xsec_dict[process][ZT].append([incoming_energy, cross_section[ZT]])
        ####=====------ FIND MAX ------=====####

        # Save sampling and cross section dictionaries to mother directory
        with open(params['save_location'] + '/sm_maps.pkl', 'wb') as f:
            pickle.dump(final_sampling_dict, f)
        with open(params['save_location'] + '/sm_xsec.pkl', 'wb') as f:
            pickle.dump(final_xsec_dict, f)
    print("Saved cross sections to " + params['save_location'] + "/sm_xsecs.pkl")
    print("Saved samples to " + params['save_location'] + "/sm_maps.pkl")
    return



startTime = datetime.now()




if __name__ == "__main__":
    #List of command line arguments
    parser = argparse.ArgumentParser(description='Process VEGAS integrators, find maxes etc', formatter_class = argparse.ArgumentDefaultsHelpFormatter)    
    # mandatory parameters    
    parser.add_argument('-import_directory', type=str, help='directory to import files from (path relative to main PETITE directory)', required=True)
    # optional parameters
    parser.add_argument('-A', type=float, default=12, help='atomic mass number')
    parser.add_argument('-Z', type=float, action='append', default=[6.0], help='atomic number of targets to save')
    #parser.add_argument('-Z', type=list, default=[6], help='atomic number of targets to save')
    parser.add_argument('-mT', type=float, default=11.178, help='nuclear target mass in GeV')
    parser.add_argument('-process', type=str, default='DarkBrem', help='processes to be run, if mV non-zero only DarkBrem \
        (choose from "PairProd", "Brem", "DarkBrem", "Comp", "Ann")')

    parser.add_argument('-save_location', type=str, default='cooked_integrators', help='directory to save integrators in (path relative to main PETITE directory)')
    parser.add_argument('-verbosity', type=bool, default=False, help='verbosity mode')
    parser.add_argument('-neval', type=int, default=300, help='neval value to provide to VEGAS for making integrator objects', required=True)
    parser.add_argument('-n_trials', type=int, default=100, help='number of evaluations to perform for estimating cross-section', required=True)

    args = parser.parse_args()
    print(args)
    if "all" in args.process:
        processes_to_do = ['PairProd', 'Comp', 'Ann', 'Brem', 'Moller', 'Bhabha']
    else:
        processes_to_do = [args.process]
    params = {'A': args.A, 'Z_T': np.unique(args.Z), 'mT': args.mT, 'process':processes_to_do, 
              'import_directory': args.import_directory, 'save_location': args.save_location, 'verbosity_mode': args.verbosity,
              'neval':args.neval, 'n_trials':args.n_trials}
    main(params)

    print("Run Time of Script:  ", datetime.now() - startTime)
