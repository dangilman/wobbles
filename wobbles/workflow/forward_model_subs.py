from wobbles.workflow.compute_distribution_function import compute_df
from wobbles.workflow.integrate_single_orbit import integrate_orbit
from wobbles.workflow.generate_perturbing_subhalos import *
from wobbles.potential_extension import PotentialExtension
from wobbles.disc import Disc

import numpy as np

import galpy
from galpy.potential import NFWPotential
from galpy.potential import MWPotential2014

import pickle
from scipy.stats.kde import gaussian_kde
import sys

f = open('./saved_potentials/MW14pot_100', "rb")
potential_global = pickle.load(f)
f.close()

galactic_potential = potential_global.galactic_potential

vla_subhalo_phase_space = np.loadtxt('vl2_halos_scaled.dat')
kde = gaussian_kde(vla_subhalo_phase_space, bw_method=0.1)

t_orbit = -1.64  # Gyr
N_tsteps = 1200
time_Gyr = np.linspace(0., t_orbit, N_tsteps) * apu.Gyr

def sample_params():

    nfw_norm = np.random.uniform(0.15, 0.45)
    disk_norm = np.random.uniform(0.45, 0.75)
    sag_mass_scale = np.random.uniform(0.3, 3.)
    f_sub = np.random.uniform(0.0, 0.1)
    vdis = np.random.uniform(15, 35)

    return (nfw_norm, disk_norm, sag_mass_scale, f_sub, vdis)

def sample_sag_orbit():

    orbit_init_sag = [283. * apu.deg, -30. * apu.deg, 26. * apu.kpc,
                      -2.6 * apu.mas / apu.yr, -1.3 * apu.mas / apu.yr,
                      140. * apu.km / apu.s]  # Initial conditions of the satellite
    return orbit_init_sag

def run(run_index, output_folder_name):
    # f is the mass fraction contained in halos between 10^6 and 10^10, CDM prediction is a few percent

    params_sampled = sample_params()
    [nfw_norm, disk_norm, sag_mscale, f_sub, velocity_dispersion] = params_sampled
    f = open('./saved_potentials/tabulated_MWpot', "rb")
    tabulated_potential = pickle.load(f)
    f.close()
    potential_local = tabulated_potential.evaluate(nfw_norm, disk_norm)

    m_host = 1.3 * 10 ** 12
    mlow, mhigh = 5 * 10 ** 6, 5 * 10 ** 9
    log_slope = -1.9
    N_halos = normalization(f_sub, log_slope, m_host, mlow, mhigh)
    sample_orbits_0 = generate_sample_orbits_kde(N_halos, kde, galactic_potential, time_Gyr)
    print('generated ' + str(N_halos) + ' halos... ')
    #######################################

    rs_host, r_core = 30, 30.
    args, func = (rs_host, r_core), core_nfw_pdf
    inds_keep = filter_orbits_NFW(sample_orbits_0, time_Gyr, func, args)
    print('removed ' + str(N_halos - len(inds_keep)) + ' halos from r < ' + str(r_core) + ' kpc...')
    sample_orbits_1 = [sample_orbits_0[idx] for idx in inds_keep]
    # get orbits that passed within dr_max of the sun in the last t_orbit years
    dr_max = 8  # kpc
    nearby_orbits_1_inds, _ = passed_near_solar_neighorhood(sample_orbits_1, time_Gyr, potential_global, R_solar=8,
                                                     dr_max=dr_max, pass_through_disk_limit=3, tdep=True)
    nearby_orbits_1 = [sample_orbits_0[idx] for idx in nearby_orbits_1_inds]
    n_nearby_1 = len(nearby_orbits_1)
    print('kept ' + str(n_nearby_1) + ' halos... ')
    #######################################

    halo_masses_1 = sample_mass_function(n_nearby_1, log_slope, mlow, mhigh)
    halo_concentrations_1 = sample_concentration(halo_masses_1)

    halo_potentials_1 = []
    for m, c in zip(halo_masses_1, halo_concentrations_1):
        halo_potentials_1.append(NFWPotential(mvir=m / 10 ** 12, conc=c))

    orbit_init_sag = sample_sag_orbit()
    sag_orbit_phsical_off = integrate_orbit(orbit_init_sag, galactic_potential, time_Gyr)
    sag_orbit = [sag_orbit_phsical_off]

    halo_orbit_list_physical_off_1 = []
    for orb in nearby_orbits_1:
        orb.turn_physical_off()
        halo_orbit_list_physical_off_1.append(orb)

    a_ref_dm = 2.1
    a_ref_stellar = 0.45
    m_sag_dm = 5e9 * sag_mscale
    m_sag_stellar = m_sag_dm/20
    rs_scale = sag_mscale ** 1./3
    a_sag, a_stellar = a_ref_dm * rs_scale, a_ref_stellar * rs_scale

    sag_potential_1 = galpy.potential.HernquistPotential(amp=m_sag_dm * apu.M_sun, a=a_sag * apu.kpc)
    sag_potential_2 = galpy.potential.HernquistPotential(amp=m_sag_stellar * apu.M_sun, a=a_stellar * apu.kpc)
    sag_potential = [sag_potential_1 + sag_potential_2]
    galpy.potential.turn_physical_off(sag_potential)

    disc = Disc(potential_local, potential_global)
    time_internal_units = sag_orbit_phsical_off.time()

    perturber_orbits = sag_orbit + halo_orbit_list_physical_off_1
    perturber_potentials = sag_potential + halo_potentials_1
    dF, delta_J, force = compute_df(disc, time_internal_units,
                                    perturber_orbits, perturber_potentials, velocity_dispersion, verbose=False)

    path_base = './output/forward_model_samples/'

    run_index = int(run_index)
    asymmetry, mean_vz = dF.A, dF.mean_v_relative

    with open(path_base + 'asymmetry_' + str(run_index) + '.txt', 'a') as f:
        string_to_write = ''
        for ai in asymmetry:
            string_to_write += str(np.round(ai, 5)) + ' '
        string_to_write += '\n'
        f.write(string_to_write)

    with open(path_base + 'meanvz_' + str(run_index) + '.txt', 'a') as f:
        string_to_write = ''
        for vzi in mean_vz:
            string_to_write += str(np.round(vzi, 5)) + ' '
        string_to_write += '\n'
        f.write(string_to_write)

    with open(path_base + 'params_' + str(run_index) + '.txt', 'a') as f:
        string_to_write = ''
        for param_val in params_sampled:
            string_to_write += str(np.round(param_val, 5)) + ' '
        string_to_write += '\n'
        f.write(string_to_write)
#
Nreal = 200
for iter in range(Nreal):
    print(str(Nreal - iter) + ' remaining...')
    run(1.)
