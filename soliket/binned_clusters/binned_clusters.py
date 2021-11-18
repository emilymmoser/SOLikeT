from soliket.binned_clusters.binned_poisson import BinnedPoissonLikelihood
from scipy import interpolate, integrate, special
from scipy.interpolate import interp1d
from typing import Optional
import numpy as np
import math as m
import time as t
import os, sys
import multiprocessing
import astropy.table as atpy
from astropy.io import fits
from functools import partial

pi = 3.1415926535897932384630
rhocrit0 = 2.7751973751261264e11 # [h2 msun Mpc-3]
c_ms = 3e8                       # [m s-1]
Mpc = 3.08568025e22              # [m]
G = 6.67300e-11                  # [m3 kg-1 s-2]
msun = 1.98892e30                # [kg]
m_pivot = 3.e14*msun

class BinnedClusterLikelihood(BinnedPoissonLikelihood):

    name = "BinnedCluster"
    data_path: Optional[str] = None
    test_cat_file: Optional[str] = None
    test_Q_file: Optional[str] = None
    test_rms_file: Optional[str] = None
    cat_file: Optional[str] = None
    Q_file: Optional[str] = None
    tile_file: Optional[str] = None
    rms_file: Optional[str] = None
    choose_dim: Optional[str] = None
    single_tile_test: Optional[str] = None
    Q_optimise: Optional[str] = None

    params = {"tenToA0":None, "B0":None, "scatter_sz":None, "bias_sz":None}

    def initialize(self):

        print('\r :::::: this is initialisation in binned_clusters.py')
        print('\r :::::: reading catalogue')

        # SNR cut
        self.qcut = 5.

        # mass bin
        self.lnmmin = np.log(1e13)
        self.lnmmax = np.log(1e16)
        self.dlnm = 0.05
        self.marr = np.arange(self.lnmmin+(self.dlnm/2.), self.lnmmax, self.dlnm)
        #this is to be consist with szcounts.f90 - maybe switch to linsapce?

        print('\r Number of mass bins : ', len(self.marr))

        single_tile = self.single_tile_test
        dimension = self.choose_dim
        Q_opt = self.Q_optimise
        self.data_directory = self.data_path

        if single_tile == 'yes':
            self.datafile = self.test_cat_file
            print(" SO test only for a single tile")
        else:
            self.datafile = self.cat_file
            print(" SO for a full map")

        if dimension == '2D':
            print(" 2D likelihood as a function of redshift and signal-to-noise")
        else:
            print(" 1D likelihood as a function of redshift")

        # reading catalogue
        list = fits.open(os.path.join(self.data_directory, self.datafile))
        data = list[1].data
        zcat = data.field("redshift")
        qcat = data.field("SNR")
        qcut = self.qcut

        Ncat = len(zcat)
        print('\r Total number of clusters in catalogue = ', Ncat)
        print('\r SNR cut = ', qcut)

        z = zcat[qcat >= qcut]
        snr = qcat[qcat >= qcut]

        Ncat = len(z)
        print('\r Number of clusters above the SNR cut = ', Ncat)
        print('\r The highest redshift = %.2f' %z.max())

        # redshift bin for N(z)
        zmax = roundup(z.max(), 1)
        zarr = np.arange(0, zmax + 0.1, 0.1)
        if zarr[0] == 0 : zarr[0] = 1e-5
        self.zarr = zarr
        print("\r Number of redshift bins = ", len(zarr)-1)

        # redshift binning
        zmin = 0.
        dz = zarr[2] - zarr[1]
        zmax = zmin + dz
        delNcat = np.zeros(len(zarr))

        i = 0
        j = 0
        for i in range(len(zarr)-2): # filling redshift bins except for the last bin
            for j in range(Ncat):
                if z[j] >= zmin and z[j] < zmax :
                    delNcat[i] += 1.
            zmin = zmin + dz
            zmax = zmax + dz

        # the last bin contains all z greater than what in the previous bin
        i = len(zarr) - 2
        zmin = zmax - dz
        j = 0
        for j in range(Ncat):
            if z[j] >= zmin :
                delNcat[i] += 1

        print("\r Catalogue N")
        for i in range(len(zarr)):
            print(i, delNcat[i])
        print(delNcat.sum())

        self.delNcat = zarr, delNcat

        # SNR bin
        logqmin = 0.6  # log10(5) = 0.699
        logqmax = 2.0  # log10(93.46) = 1.970
        dlogq = 0.25   # manually for now

        Nq = int((logqmax - logqmin)/dlogq) + 1
        qi = logqmin + dlogq/2.
        qarr = np.zeros(Nq + 1)

        i = 0
        for i in range(Nq+1):
            qarr[i] = qi
            qi = qi + dlogq

        if dimension == "2D":
            print('\r The lowest SNR = %.2f' %snr.min())
            print('\r The highest SNR = %.2f' %snr.max())
            print("\r Number of SNR bins = ", Nq)
            print("\r Edges of SNR bins = ", 10**(qarr - dlogq/2.))

        zmin = 0.
        zmax = zmin + dz
        delN2Dcat = np.zeros((len(zarr), Nq+1))

        i = 0
        j = 0
        for i in range(len(zarr)-1):
           for j in range(Nq):
                qmin = qarr[j] - dlogq/2.
                qmax = qarr[j] + dlogq/2.
                qmin = 10.**qmin
                qmax = 10.**qmax

                for k in range(Ncat):
                    if z[k] >= zmin and z[k] < zmax and snr[k] >= qmin and snr[k] < qmax :
                        delN2Dcat[i,j] += 1

           # the last bin contains all S/N greater than what in the previous bin
           j = Nq - 1
           qmin = qmax

           for k in range(Ncat):
               if z[k] >= zmin and z[k] < zmax and snr[k] >= qmin :
                   delN2Dcat[i,j] += 1

           zmin = zmin + dz
           zmax = zmax + dz

        # the last bin contains all z greater than what in the previous bin
        for k in range(Ncat):
            for j in range(Nq):
                 qmin = qarr[j] - dlogq/2.
                 qmax = qarr[j] + dlogq/2.
                 qmin = 10.**qmin
                 qmax = 10.**qmax
                 if z[k] >= zarr[-1] and snr[k] >= qmin and snr[k] < qmax :
                     delN2Dcat[len(zarr)-2,j] += 1

        if dimension == "2D":
            print("\r Catalogue N in SNR bins")
            j = 0
            for j in range(Nq+1):
                    print("", j, delN2Dcat[:,j].sum())

        self.Nq = Nq
        self.qarr = qarr
        self.dlogq = dlogq
        self.delN2Dcat = zarr, qarr, delN2Dcat

        print('\r :::::: loading files describing selection function')
        print('\r :::::: reading Q as a function of theta')
        if single_tile =='yes':
            self.datafile_Q = self.test_Q_file
            list = fits.open(os.path.join(self.data_directory, self.datafile_Q))
            data = list[1].data
            self.tt500 = data.field("theta500Arcmin")
            self.Q = data.field("PRIMARY")
            assert len(self.tt500) == len(self.Q)
            print("\r Number of Q function = ", self.Q.ndim)

        else:
            # for quick reading theta and Q data is saved first and just called
            self.datafile_Q = self.Q_file
            Qfile = np.load(os.path.join(self.data_directory, self.datafile_Q))
            self.tt500 = Qfile['theta']
            self.allQ = Qfile['Q']

            assert len(self.tt500) == len(self.allQ[:,0])

            if Q_opt == 'yes':
                self.Q = np.mean(self.allQ, axis=1)
                print("\r Number of Q functions = ", self.Q.ndim)
                print("\r Using one averaged Q function for optimisation")
            else:
                self.Q = self.allQ
                print("\r Number of Q functions = ", len(self.Q[0]))


        print('\r :::::: reading noise data')
        if single_tile == 'yes':
            self.datafile_rms = self.test_rms_file

            list = fits.open(os.path.join(self.data_directory, self.datafile_rms))
            data = list[1].data
            self.skyfracs = data.field("areaDeg2")*np.deg2rad(1.)**2
            self.noise = data.field("y0RMS")
            print("\r Number of sky patches = ", self.skyfracs.size)

        else:
            # for convenience,
            # save a down sampled version of rms txt file and read it directly
            # this way is a lot faster
            # could recreate this file with different downsampling as well
            # tile name is replaced by consecutive number from now on

            self.datafile_rms = self.rms_file
            file_rms = np.loadtxt(os.path.join(self.data_directory, self.datafile_rms))
            self.noise = file_rms[:,0]
            self.skyfracs = file_rms[:,1]
            self.tname = file_rms[:,2]
            print("\r Number of tiles = ", len(np.unique(self.tname)))

            downsample = 50
            print("\r Noise map is downsampled to speed up a completeness compuation by %d" %downsample)
            print("\r Number of sky patches = ", self.skyfracs.size)

        print("\r Entire survey area = ", self.skyfracs.sum()/(np.deg2rad(1.)**2.), "deg2")

        super().initialize()

    def get_requirements(self):
        return {"Hubble":  {"z": self.zarr},
                "angular_diameter_distance": {"z": self.zarr},
                "Pk_interpolator": {"z": self.zarr,
                                    "k_max": 4.0,
                                    "nonlinear": False,
                                    "hubble_units": False,
                                    "k_hunit": False,
                                    "vars_pairs": [["delta_nonu", "delta_nonu"]]},
                "H0":None}

    def _get_data(self):
        return self.delNcat, self.delN2Dcat

    def _get_om(self):
        return (self.theory.get_param("omch2") + self.theory.get_param("ombh2") + self.theory.get_param("omnuh2"))/((self.theory.get_param("H0")/100.0)**2)

    def _get_Ez(self):
        return self.theory.get_Hubble(self.zarr)/self.theory.get_param("H0")

    def _get_DAz(self):
        return self.theory.get_angular_diameter_distance(self.zarr)

    def _get_dndlnm(self, pk_intp, **params_values_dict):

        h = self.theory.get_param("H0")/100.0
        Ez = self._get_Ez()
        om = self._get_om()
        rhom0 = rhocrit0 * om
        zarr = self.zarr
        marr = self.marr

        # redshift bin for P(z,k)
        zpk = np.linspace(0, 3., 141)
        if zpk[0] == 0. : zpk[0] = 1e-5

        k = np.logspace(-4, np.log10(5), 200, endpoint=False)
        pks0 = pk_intp.P(zpk, k)

        def pks_zbins(newz):
            i = 0
            newp = np.zeros((len(newz),len(k)))
            for i in range(k.size):
                tck = interpolate.splrep(zpk, pks0[:,i])
                newp[:,i] = interpolate.splev(newz, tck)
            return newp
        pks = pks_zbins(zarr)

        pks *= h**3.
        kh = k/h

        def radius(M):
            return (0.75*M/pi/rhom0)**(1./3.)

        def win(x):
            return 3.*(np.sin(x) - x*np.cos(x))/(x**3.)

        def win_prime(x):
            return 3.*np.sin(x)/(x**2.) - 9.*(np.sin(x) - x*np.cos(x))/(x**4.)

        def sigma_sq(R, k):
            integral = np.zeros((len(k), len(marr), len(zarr)))
            i = 0
            for i in range(k.size):
                integral[i,:,:] = np.array((k[i]**2.)*pks[:,i]*(win(k[i]*R)**2.))
            return integrate.simps(integral, k, axis=0)/(2.*pi**2.)

        def sigma_sq_prime(R, k):
            # this is derivative of sigmaR squared
            # so 2 * sigmaR * dsigmaR/dR
            integral = np.zeros((len(k), len(marr), len(zarr)))
            i = 0
            for i in range(k.size):
                integral[i,:,:] = np.array((k[i]**2.)*pks[:,i]*2.*k[i]*win(k[i]*R)*win_prime(k[i]*R))
            return integrate.simps(integral, k, axis=0)/(2.*pi**2.)

        def tinker(sgm, zarr):

            total = 9

            delta  = np.zeros(total)
            par_aa = np.zeros(total)
            par_a  = np.zeros(total)
            par_b  = np.zeros(total)
            par_c  = np.zeros(total)

            delta[0] = 200
            delta[1] = 300
            delta[2] = 400
            delta[3] = 600
            delta[4] = 800
            delta[5] = 1200
            delta[6] = 1600
            delta[7] = 2400
            delta[8] = 3200

            par_aa[0] = 0.186
            par_aa[1] = 0.200
            par_aa[2] = 0.212
            par_aa[3] = 0.218
            par_aa[4] = 0.248
            par_aa[5] = 0.255
            par_aa[6] = 0.260
            par_aa[7] = 0.260
            par_aa[8] = 0.260

            par_a[0] = 1.47
            par_a[1] = 1.52
            par_a[2] = 1.56
            par_a[3] = 1.61
            par_a[4] = 1.87
            par_a[5] = 2.13
            par_a[6] = 2.30
            par_a[7] = 2.53
            par_a[8] = 2.66

            par_b[0] = 2.57
            par_b[1] = 2.25
            par_b[2] = 2.05
            par_b[3] = 1.87
            par_b[4] = 1.59
            par_b[5] = 1.51
            par_b[6] = 1.46
            par_b[7] = 1.44
            par_b[8] = 1.41

            par_c[0] = 1.19
            par_c[1] = 1.27
            par_c[2] = 1.34
            par_c[3] = 1.45
            par_c[4] = 1.58
            par_c[5] = 1.80
            par_c[6] = 1.97
            par_c[7] = 2.24
            par_c[8] = 2.44

            delta = np.log10(delta)

            dso = 200.
            omz = om*((1. + zarr)**3.)/(Ez**2.)

            tck1 = interpolate.splrep(delta, par_aa)
            tck2 = interpolate.splrep(delta, par_a)
            tck3 = interpolate.splrep(delta, par_b)
            tck4 = interpolate.splrep(delta, par_c)

            par1 = interpolate.splev(np.log10(dso), tck1)
            par2 = interpolate.splev(np.log10(dso), tck2)
            par3 = interpolate.splev(np.log10(dso), tck3)
            par4 = interpolate.splev(np.log10(dso), tck4)

            alpha = 10.**(-((0.75/np.log10(dso/75.))**1.2))
            A     = par1*((1. + zarr)**(-0.14))
            a     = par2*((1. + zarr)**(-0.06))
            b     = par3*((1. + zarr)**(-alpha))
            c     = par4*np.ones(zarr.size)

            return A * (1. + (sgm/b)**(-a)) * np.exp(-c/(sgm**2.))

        dRdM = radius(np.exp(marr))/(3.*np.exp(marr))
        dRdM = dRdM[:,None]
        R = radius(np.exp(marr))[:,None]
        sigma = sigma_sq(R, kh)**0.5
        sigma_prime = sigma_sq_prime(R, kh)
        return  -rhom0 * tinker(sigma, zarr) * dRdM * (sigma_prime/(2.*sigma**2.))

    def _get_dVdzdO(self):

        dAz = self._get_DAz()
        Hz = self.theory.get_Hubble(self.zarr)
        h = self.theory.get_param("H0") / 100.0
        dVdzdO = (c_ms/1e3)*(((1. + self.zarr)*dAz)**2.)/Hz
        return dVdzdO * h**3.

    def _get_M500c_from_M200m(self, M200m, z):

        H0 = self.theory.get_param("H0") / Mpc
        h = self.theory.get_param("H0") / 100.
        om = self._get_om()

        def Eh(zz):
            return np.sqrt(om * np.power(1 + zz, 3.) + (1 - om))

        def growth(zz):
            zmax = 1000
            dz = 0.1
            zs = np.arange(zz, zmax, dz)
            y = (1 + zs)/ np.power(H0 * Eh(zs), 3)
            return Eh(zz) * integrate.simps(y, zs)

        def normalised_growth(zz):
            return growth(zz)/growth(0.)

        def rho_crit(zz):
            return (3. / 8. * np.pi * G) * np.power(H0 * Eh(zz), 2.)

        def rho_mean(zz):
            z0 = 0
            return rho_crit(z0) * om * np.power(1 + zz, 3.)

        Dz = []
        for i in range(len(z)):
            Dz.append(normalised_growth(z[i]))
        Dz = np.array(Dz)

        rho_c = rho_crit(z)
        rho_m = rho_mean(z)
        M200m = M200m[:,None]

        peak = (1. / Dz) * (1.12 * np.power(M200m / (5e13 / h), 0.3) + 0.53)
        c200m = np.power(Dz, 1.15) * 9. * np.power(peak, -0.29)
        R200m = np.power(3./(4. * np.pi) * M200m / (200 * rho_m), 1./3.)
        rs = R200m / c200m
        x = np.linspace(1e-3, 10, 1000)
        fx = np.power(x, 3.) * (np.log(1. + 1./x) - 1./(1. + x))

        xf_intp = interpolate.splrep(fx, x)
        fx_intp = interpolate.splrep(x, fx)

        f_rs_R500c = (500. * rho_c) / (200. * rho_m) * interpolate.splev(1./c200m, fx_intp)
        x_rs_R500c = interpolate.splev(f_rs_R500c, xf_intp)

        R500c = rs / x_rs_R500c
        return (4. * np.pi / 3.) * np.power(R500c, 3.) * 500. * rho_c

    def _get_integrated(self, pk_intp, **params_values_dict):

        h = self.theory.get_param("H0") / 100.0
        zarr = self.zarr
        marr = np.exp(self.marr)
        dlnm = self.dlnm

        M500c = self._get_M500c_from_M200m(marr, zarr)
        marr = M500c

        y0 = self._get_y0(marr, **params_values_dict)
        dVdzdO = self._get_dVdzdO()
        dndlnm = self._get_dndlnm(pk_intp, **params_values_dict)
        surveydeg2 = self.skyfracs.sum()
        intgr = dndlnm * dVdzdO * surveydeg2
        intgr = intgr.T

        c = self._get_completeness(marr, zarr, y0, **params_values_dict)

        delN = np.zeros(len(zarr))
        i = 0
        j = 0
        for i in range(len(zarr)-1):
            for j in range(len(marr)):
                delN[i] += 0.5*(intgr[i,j]*c[i,j] + intgr[i+1,j]*c[i+1,j])*(zarr[i+1] - zarr[i])*dlnm
            print(i, delN[i])
        print("\r Total predicted N = ", delN.sum())

        return delN


    def _get_integrated2D(self, pk_intp, **params_values_dict):

        h = self.theory.get_param("H0") / 100.0
        zarr = self.zarr
        marr = np.exp(self.marr)
        dlnm = self.dlnm
        Nq = self.Nq

        M500c = self._get_M500c_from_M200m(marr, zarr)
        marr = M500c

        y0 = self._get_y0(marr, **params_values_dict)
        dVdzdO = self._get_dVdzdO()
        dndlnm = self._get_dndlnm(pk_intp, **params_values_dict)
        surveydeg2 = self.skyfracs.sum()
        intgr = dndlnm*dVdzdO*surveydeg2
        intgr = intgr.T

        cc = []
        kk = 0
        for kk in range(Nq):
            cc.append(self._get_completeness2D(marr, zarr, y0, kk, **params_values_dict))
        cc = np.asarray(cc)

        delN2D = np.zeros((len(zarr), Nq+1))
        i = 0
        j = 0
        kk = 0
        for kk in range(Nq):
            for i in range(len(zarr)-1):
                for j in range(len(marr)):
                    delN2D[i,kk] += 0.5*(intgr[i,j]*cc[kk,i,j] + intgr[i+1,j]*cc[kk,i+1,j])*(zarr[i+1] - zarr[i])*dlnm
            #print(kk, delN2D[:,kk].sum())

        for i in range(len(zarr)):
            print(i, delN2D[i,:].sum())
        print("\r Total predicted 2D N = ", delN2D.sum())

        return delN2D


    def _get_theory(self, pk_intp, **params_values_dict):

        start = t.time()

        if self.choose_dim == '1D':
            delN = self._get_integrated(pk_intp, **params_values_dict)
        else:
            delN = self._get_integrated2D(pk_intp, **params_values_dict)

        elapsed = t.time() - start
        print("\r ::: theory N calculation took %.1f seconds" %elapsed)

        return delN


    # y-m scaling relation for completeness
    def _get_y0(self, mass, **params_values_dict):

        single_tile = self.single_tile_test
        Q_opt = self.Q_optimise

        A0 = params_values_dict["tenToA0"]
        B0 = params_values_dict["B0"]
        bias = params_values_dict["bias_sz"]

        Ez = self._get_Ez()
        h = self.theory.get_param("H0") / 100.0
        mb = mass * bias
        mpivot = 3e14 * h

        def theta(m):
            thetastar = 6.997
            alpha_theta = 1./3.
            DAz = self._get_DAz() * h
            H0 = self.theory.get_param("H0")
            ttstar = thetastar * (H0/70.)**(-2./3.)
            return ttstar*(m/3.e14*(100./H0))**alpha_theta * Ez**(-2./3.) * (100.*DAz/500/H0)**(-1.)

        def splQ(x):
            if single_tile == 'yes' or Q_opt == 'yes':
                tck = interpolate.splrep(self.tt500, self.Q)
                newQ = interpolate.splev(x, tck)
            else:
                newQ = []
                i = 0
                for i in range(len(self.Q[0])):
                    tck = interpolate.splrep(self.tt500, self.Q[:,i])
                    newQ.append(interpolate.splev(x, tck))
            return np.asarray(np.abs(newQ))

        def rel(m):
            mm = m / mpivot
            t = -0.008488*(mm*Ez[:,None])**(-0.585)
            return 1 + 3.79*t - 28.2*(t**2.)

        if single_tile == 'yes' or Q_opt == 'yes':
            y0 = A0 * (Ez**2.) * (mb / mpivot)**(1. + B0) * splQ(theta(mb))
            y0 = y0.T
        else:
            arg = A0 * (Ez**2.) * (mb[:,None] / mpivot)**(1. + B0)
            y0 = arg[:,:,None] * splQ(theta(mb)) * rel(mb).T[:,:,None]
        return y0

    # completeness 1D
    def _get_completeness(self, marr, zarr, y0, **params_values_dict):

        scatter = params_values_dict["scatter_sz"]
        noise = self.noise
        qcut = self.qcut
        skyfracs = self.skyfracs/self.skyfracs.sum()
        Npatches = len(skyfracs)
        single_tile = self.single_tile_test
        Q_opt = self.Q_optimise
        if single_tile == 'no' and Q_opt == 'no': tilename = self.tname

        if scatter == 0.:
            a_pool = multiprocessing.Pool()
            completeness = a_pool.map(partial(get_comp_zarr,
                                        Nm=len(marr),
                                        qcut=qcut,
                                        noise=noise,
                                        skyfracs=skyfracs,
                                        lnyy=None,
                                        dyy=None,
                                        yy=None,
                                        y0=y0,
                                        temp=None,
                                        single_tile=single_tile,
                                        tile=None if single_tile == 'yes' or Q_opt == 'yes' else tilename,
                                        Q_opt=Q_opt,
                                        scatter=scatter),range(len(zarr)))
        else :
            lnymin = -25.     #ln(1e-10) = -23
            lnymax = 0.       #ln(1e-2) = -4.6
            dlny = 0.05
            Ny = m.floor((lnymax - lnymin)/dlny)
            temp = []
            yy = []
            lnyy = []
            dyy = []
            i = 0
            lny = lnymin

            if single_tile == 'yes' or Q_opt == "yes":

                for i in range(Ny):
                    y = np.exp(lny)
                    arg = (y - qcut*noise)/np.sqrt(2.)/noise
                    erfunc = (special.erf(arg) + 1.)/2.
                    temp.append(np.dot(erfunc, skyfracs))
                    yy.append(y)
                    lnyy.append(lny)
                    dyy.append(np.exp(lny + dlny*0.5) - np.exp(lny - dlny*0.5))
                    lny += dlny
                temp = np.asarray(temp)
                yy = np.asarray(yy)
                lnyy = np.asarray(lnyy)
                dyy = np.asarray(dyy)

            else:
                for i in range(Ny):
                    y = np.exp(lny)
                    j = 0
                    for j in range(Npatches):
                        arg = (y - qcut*noise[j])/np.sqrt(2.)/noise[j]
                        erfunc = (special.erf(arg) + 1.)/2.
                        temp.append(erfunc*skyfracs[j])
                        yy.append(y)
                        lnyy.append(lny)
                        dyy.append(np.exp(lny + dlny*0.5) - np.exp(lny - dlny*0.5))
                    lny += dlny
                temp = np.asarray(np.array_split(temp, Npatches))
                yy = np.asarray(np.array_split(yy, Npatches))
                lnyy = np.asarray(np.array_split(lnyy, Npatches))
                dyy = np.asarray(np.array_split(dyy, Npatches))

            a_pool = multiprocessing.Pool()
            completeness = a_pool.map(partial(get_comp_zarr,
                                                Nm=len(marr),
                                                qcut=None,
                                                noise=None,
                                                skyfracs=skyfracs,
                                                lnyy=lnyy,
                                                dyy=dyy,
                                                yy=yy,
                                                y0=y0,
                                                temp=temp,
                                                single_tile=single_tile,
                                                tile=None if single_tile == 'yes' or Q_opt == 'yes' else tilename,
                                                Q_opt=Q_opt,
                                                scatter=scatter),range(len(zarr)))
        a_pool.close()
        comp = np.asarray(completeness)
        comp[comp < 0.] = 0.
        comp[comp > 1.] = 1.

        return comp

    # completeness 2D
    def _get_completeness2D(self, marr, zarr, y0, qbin, **params_values_dict):

        scatter = params_values_dict["scatter_sz"]
        noise = self.noise
        qcut = self.qcut
        skyfracs = self.skyfracs/self.skyfracs.sum()
        Npatches = len(skyfracs)
        single_tile = self.single_tile_test
        Q_opt = self.Q_optimise
        if single_tile == 'no' and Q_opt == 'no': tilename = self.tname

        Nq = self.Nq
        qarr = self.qarr
        dlogq = self.dlogq

        if scatter == 0.:
            a_pool = multiprocessing.Pool()
            completeness = a_pool.map(partial(get_comp_zarr2D,
                                            Nm=len(marr),
                                            qcut=qcut,
                                            noise=noise,
                                            skyfracs=skyfracs,
                                            y0=y0,
                                            Nq=Nq,
                                            qarr=qarr,
                                            dlogq=dlogq,
                                            qbin=qbin,
                                            lnyy=None,
                                            dyy=None,
                                            yy=None,
                                            temp=None,
                                            single_tile=single_tile,
                                            Q_opt=Q_opt,
                                            tile=None if single_tile == 'yes' or Q_opt == 'yes' else tilename,
                                            scatter=scatter),range(len(zarr)))


        else:
            lnymin = -25.     #ln(1e-10) = -23
            lnymax = 0.       #ln(1e-2) = -4.6
            dlny = 0.05
            Ny = m.floor((lnymax - lnymin)/dlny)
            temp = []
            yy = []
            lnyy = []
            dyy = []
            lny = lnymin
            i = 0

            if single_tile == 'yes' or Q_opt == "yes":

                for i in range(Ny):
                    yy0 = np.exp(lny)

                    kk = qbin
                    qmin = qarr[kk] - dlogq/2.
                    qmax = qarr[kk] + dlogq/2.
                    qmin = 10.**qmin
                    qmax = 10.**qmax

                    if kk == 0:
                        cc = get_erf(yy0, noise, qcut)*(1. - get_erf(yy0, noise, qmax))
                    elif kk == Nq-1:
                        cc = get_erf(yy0, noise, qcut)*get_erf(yy0, noise, qmin)
                    else:
                        cc = get_erf(yy0, noise, qcut)*get_erf(yy0, noise, qmin)*(1. - get_erf(yy0, noise, qmax))

                    temp.append(np.dot(cc.T, skyfracs))
                    yy.append(yy0)
                    lnyy.append(lny)
                    dyy.append(np.exp(lny + dlny*0.5) - np.exp(lny - dlny*0.5))
                    lny += dlny

                temp = np.asarray(temp)
                yy = np.asarray(yy)
                lnyy = np.asarray(lnyy)
                dyy = np.asarray(dyy)

            else:

                for i in range(Ny):
                    yy0 = np.exp(lny)

                    kk = qbin
                    qmin = qarr[kk] - dlogq/2.
                    qmax = qarr[kk] + dlogq/2.
                    qmin = 10.**qmin
                    qmax = 10.**qmax

                    j = 0
                    for j in range(Npatches):
                        if kk == 0:
                            cc = get_erf(yy0, noise[j], qcut)*(1. - get_erf(yy0, noise[j], qmax))
                        elif kk == Nq:
                            cc = get_erf(yy0, noise[j], qcut)*get_erf(yy0, noise[j], qmin)
                        else:
                            cc = get_erf(yy0, noise[j], qcut)*get_erf(yy0, noise[j], qmin)*(1. - get_erf(yy0, noise[j], qmax))

                        temp.append(cc*skyfracs[j])
                        yy.append(yy0)
                        lnyy.append(lny)
                        dyy.append(np.exp(lny + dlny*0.5) - np.exp(lny - dlny*0.5))
                    lny += dlny

                temp = np.asarray(np.array_split(temp, Npatches))
                yy = np.asarray(np.array_split(yy, Npatches))
                lnyy = np.asarray(np.array_split(lnyy, Npatches))
                dyy = np.asarray(np.array_split(dyy, Npatches))

            a_pool = multiprocessing.Pool()
            completeness = a_pool.map(partial(get_comp_zarr2D,
                                                Nm=len(marr),
                                                qcut=qcut,
                                                noise=noise,
                                                skyfracs=skyfracs,
                                                y0=y0,
                                                Nq=Nq,
                                                qarr=qarr,
                                                dlogq=dlogq,
                                                qbin=qbin,
                                                lnyy=lnyy,
                                                dyy=dyy,
                                                yy=yy,
                                                temp=temp,
                                                single_tile=single_tile,
                                                Q_opt=Q_opt,
                                                tile=None if single_tile == 'yes' or Q_opt == 'yes' else tilename,
                                                scatter=scatter),range(len(zarr)))

        a_pool.close()
        comp = np.asarray(completeness)
        comp[comp < 0.] = 0.
        comp[comp > 1.] = 1.

        return comp


def get_comp_zarr(index_z, Nm, qcut, noise, skyfracs, lnyy, dyy, yy, y0, temp, single_tile, Q_opt, tile, scatter):

    i = 0
    res = []
    for i in range(Nm):

        if scatter == 0.:

            if single_tile == 'yes' or Q_opt == 'yes':
                arg = get_erf(y0[index_z, i], noise, qcut)
            else:
                j = 0
                arg = []
                for j in range(len(skyfracs)):
                    arg.append(get_erf(y0[i, index_z, int(tile[j])-1], noise[j], qcut))
                arg = np.asarray(arg)
            res.append(np.dot(arg, skyfracs))

        else:

            fac = 1./np.sqrt(2.*pi*scatter**2)
            mu = np.log(y0)
            if single_tile == 'yes' or Q_opt == 'yes':
                arg = (lnyy - mu[index_z, i])/(np.sqrt(2.)*scatter)
                res.append(np.dot(temp, fac*np.exp(-arg**2.)*dyy/yy))
            else:
                j = 0
                args = 0.
                for j in range(len(skyfracs)):
                    arg = (lnyy[j,:] - mu[i, index_z, int(tile[j])-1])/(np.sqrt(2.)*scatter)
                    args += np.dot(temp[j,:], fac*np.exp(-arg**2.)*dyy[j,:]/yy[j,:])
                res.append(args)

    return res

def get_comp_zarr2D(index_z, Nm, qcut, noise, skyfracs, y0, Nq, qarr, dlogq, qbin, lnyy, dyy, yy, temp, single_tile, Q_opt, tile, scatter):

    kk = qbin
    qmin = qarr[kk] - dlogq/2.
    qmax = qarr[kk] + dlogq/2.
    qmin = 10.**qmin
    qmax = 10.**qmax

    i = 0
    res = []
    for i in range(Nm):

        if scatter == 0.:

            if single_tile == 'yes' or Q_opt == "yes":
                if kk == 0:
                    erfunc = get_erf(y0[index_z,i], noise, qcut)*(1. - get_erf(y0[index_z,i], noise, qmax))
                elif kk == Nq:
                    erfunc = get_erf(y0[index_z,i], noise, qcut)*get_erf(y0[index_z,i], noise, qmin)
                else:
                    erfunc = get_erf(y0[index_z,i], noise, qcut)*get_erf(y0[index_z,i], noise, qmin)*(1. - get_erf(y0[index_z,i], noise, qmax))
            else:
                j = 0
                erfunc = []
                for j in range(len(skyfracs)):
                    if kk == 0:
                        erfunc.append(get_erf(y0[i,index_z,int(tile[j])-1], noise[j], qcut)*(1. - get_erf(y0[i,index_z,int(tile[j]-1)], noise[j], qmax)))
                    elif kk == Nq:
                        erfunc.append(get_erf(y0[i,index_z,int(tile[j])-1], noise[j], qcut)*get_erf(y0[i,index_z,int(tile[j])-1], noise[j], qmin))
                    else:
                        erfunc.append(get_erf(y0[i,index_z,int(tile[j])-1], noise[j], qcut)*get_erf(y0[i,index_z,int(tile[j])-1], noise[j], qmin)*(1. - get_erf(y0[i,index_z,int(tile[j])-1], noise[j], qmax)))
                erfunc = np.asarray(erfunc)
            res.append(np.dot(erfunc, skyfracs))

        else:

            fac = 1./np.sqrt(2.*pi*scatter**2)
            mu = np.log(y0)
            if single_tile == 'yes' or Q_opt == "yes":
                arg = (lnyy - mu[index_z,i])/(np.sqrt(2.)*scatter)
                res.append(np.dot(temp, fac*np.exp(-arg**2.)*dyy/yy))
            else:
                j = 0
                args = 0.
                for j in range(len(skyfracs)):
                    #rint("second loop", j) # most of time takes here
                    arg = (lnyy[j,:] - mu[i, index_z, int(tile[j])-1])/(np.sqrt(2.)*scatter)
                    args += np.dot(temp[j,:], fac*np.exp(-arg**2.)*dyy[j,:]/yy[j,:])
                res.append(args)

    return res

def get_erf(y, rms, cut):
    arg = (y - cut*rms)/np.sqrt(2.)/rms
    erfc = (special.erf(arg) + 1.)/2.
    return erfc

def roundup(x, places):
  d = np.power(10., places)
  if x < 0:
    return m.floor(x * d) / d
  else:
    return m.ceil(x * d) / d

class BinnedClusterLikelihoodPlanck(BinnedPoissonLikelihood):

    name = "BinnedClusterPlanck"
    plc_data_path: Optional[str] = None
    plc_cat_file: Optional[str] = None
    plc_thetas_file: Optional[str] = None
    plc_skyfracs_file: Optional[str] = None
    plc_ylims_file: Optional[str] = None
    choose_dim: Optional[str] = None

    params = {"alpha_sz":None, "ystar_sz":None, "beta_sz":None, "scatter_sz":None, "bias_sz":None}

    def initialize(self):

        print('\r :::::: this is initialisation in binned_clusters.py')
        print('\r :::::: reading Planck 2015 catalogue')

        # full sky (sky fraction handled in skyfracs file)
        self.surveydeg2 = 41253.0*3.046174198e-4
        # signal-to-noise threshold
        self.qcut = 6.

        # mass bins
        self.lnmmin = 31.
        self.lnmmax = 37.
        self.dlnm = 0.05
        self.marr = np.arange(self.lnmmin+self.dlnm/2, self.lnmmax+self.dlnm/2, self.dlnm)

        # loading the catalogue
        self.data_directory = self.plc_data_path
        self.datafile = self.plc_cat_file
        cat = np.loadtxt(os.path.join(self.data_directory, self.datafile))
        zcat = cat[:,0]
        qcat = cat[:,2]

        Ncat = len(zcat)
        print('\r Number of clusters in catalogue = ', Ncat)
        print('\r SNR cut = ', self.qcut)

        znew = []
        snrnew= []
        i = 0
        for i in range(Ncat):
            if qcat[i] > self.qcut:
                znew.append(zcat[i])
                snrnew.append(qcat[i])

        z = np.array(znew)
        snr = np.array(snrnew)
        Ncat = len(z)
        print('\r Number of clusters above the SNR cut = ', Ncat)

        # 1D catalogue
        print('\r :::::: binning clusters according to their redshifts')

        # redshift bin for N(z)
        zarr = np.linspace(0, 1, 11)
        if zarr[0] == 0 :zarr[0] = 1e-5
        self.zarr = zarr

        zmin = 0.
        dz = 0.1
        zmax = zmin + dz
        delNcat = np.zeros(len(zarr))
        i = 0
        j = 0
        for i in range(len(zarr)):
            for j in range(Ncat):
                if z[j] >= zmin and z[j] < zmax :
                    delNcat[i] += 1.
            zmin = zmin + dz
            zmax = zmax + dz

        print("\r Number of redshift bins = ", len(zarr)-1) # last bin is empty anyway
        print("\r Catalogue N = ", delNcat, delNcat.sum())

        # rescaling for missing redshift
        Nmiss = 0
        i = 0
        for i in range(Ncat):
            if z[i] < 0.:
                Nmiss += 1

        Ncat2 = Ncat - Nmiss
        print('\r Number of clusters with redshift = ', Ncat2)
        print('\r Number of clusters without redshift = ', Nmiss)

        rescale = Ncat/Ncat2

        if Nmiss != 0:
            print("\r Rescaling for missing redshifts ", rescale)

        delNcat *= rescale
        print("\r Rescaled Catalogue N = ", delNcat, delNcat.sum())

        self.delNcat = zarr, delNcat

        # 2D catalogue
        if self.choose_dim == "2D":
            print('\r :::::: binning clusters according to their SNRs')

        logqmin = 0.7  # log10[4]  = 0.778 --- min snr = 6
        logqmax = 1.5  # log10(35) = 1.505 --- max snr = 32
        dlogq = 0.25

        Nq = int((logqmax - logqmin)/dlogq) + 1  ########
        if self.choose_dim == "2D":
            print("\r Number of SNR bins = ", Nq+1)

        qi = logqmin + dlogq/2.
        qarr = np.zeros(Nq+1)

        i = 0
        for i in range(Nq+1):
            qarr[i] = qi
            qi = qi + dlogq
        if self.choose_dim == "2D":
            print("\r Center of SNR bins = ", 10**qarr)

        zmin = zarr[0]
        zmax = zmin + dz

        delN2Dcat = np.zeros((len(zarr), Nq+1))

        i = 0
        j = 0
        k = 0
        for i in range(len(zarr)):
           for j in range(Nq):
                qmin = qarr[j] - dlogq/2.
                qmax = qarr[j] + dlogq/2.
                qmin = 10.**qmin
                qmax = 10.**qmax

                for k in range(Ncat):
                    if z[k] >= zmin and z[k] < zmax and snr[k] >= qmin and snr[k] < qmax :
                        delN2Dcat[i,j] += 1

           j = Nq + 1 # the last bin contains all S/N greater than what in the previous bin
           qmin = qmax

           for k in range(Ncat):
               if z[k] >= zmin and z[k] < zmax and snr[k] >= qmin :
                   delN2Dcat[i,j] += 1

           zmin = zmin + dz
           zmax = zmax + dz

        if self.choose_dim == "2D":
            print("\r Catalogue 2D N = ", delN2Dcat.sum())
            j = 0
            for j in range(Nq+1):
                    print(j, delN2Dcat[:,j], delN2Dcat[:,j].sum())

        # missing redshifts
        i = 0
        j = 0
        k = 0
        for j in range(Nq):
            qmin = qarr[j] - dlogq/2.
            qmax = qarr[j] + dlogq/2.
            qmin = 10.**qmin
            qmax = 10.**qmax

            for k in range(Ncat):
                if z[k] == -1. and snr[k] >= qmin and snr[k] < qmax :
                    norm = 0.
                    for i in range(len(zarr)):
                        norm += delN2Dcat[i,j]
                    delN2Dcat[:,j] *= (norm + 1.)/norm

        j = Nq + 1 # the last bin contains all S/N greater than what in the previous bin
        qmin = qmax
        for k in range(Ncat):
            if z[k] == -1. and snr[k] >= qmin :
                norm = 0.
                for i in range(len(zarr)):
                    norm += delN2Dcat[i,j]
                delN2Dcat[:,j] *= (norm + 1.)/norm

        if self.choose_dim == "2D":
            print("\r Rescaled Catalogue 2D N = ", delN2Dcat.sum())
            j = 0
            for j in range(Nq+1):
                    print(j, delN2Dcat[:,j], delN2Dcat[:,j].sum())


        self.Nq = Nq
        self.qarr = qarr
        self.dlogq = dlogq
        self.delN2Dcat = zarr, qarr, delN2Dcat

        print('\r :::::: loading files describing selection function')

        self.datafile = self.plc_thetas_file
        thetas = np.loadtxt(os.path.join(self.data_directory, self.datafile))
        print('\r Number of size thetas = ', len(thetas))

        self.datafile = self.plc_skyfracs_file
        skyfracs = np.loadtxt(os.path.join(self.data_directory, self.datafile))
        print('\r Number of size skypatches = ', len(skyfracs))

        self.datafile = self.plc_ylims_file
        ylims0 = np.loadtxt(os.path.join(self.data_directory, self.datafile))
        print('\r Number of size ylims = ', len(ylims0))
        if len(ylims0) != len(thetas)*len(skyfracs):
            raise ValueError("Format error for ylims.txt \n" +\
                             "Expected rows : {} \n".format(len(thetas)*len(skyfracs)) +\
                             "Actual rows : {}".format(len(ylims0)))

        ylims = np.zeros((len(skyfracs), len(thetas)))

        i = 0
        j = 0
        k = 0
        for k in range(len(ylims0)):
            ylims[i,j] = ylims0[k]
            i += 1
            if i > len(skyfracs)-1:
                i = 0
                j += 1

        self.thetas = thetas
        self.skyfracs = skyfracs
        self.ylims = ylims

        # high resolution redshift bins
        minz = zarr[0]
        maxz = zarr[-1]
        if minz < 0: minz = 0.
        zi = minz

        # counting redshift bins
        Nzz = 0
        while zi <= maxz :
            zi = self._get_hres_z(zi)
            Nzz += 1

        Nzz += 1
        zi = minz
        zz = np.zeros(Nzz)
        for i in range(Nzz): # [0-279]
            zz[i] = zi
            zi = self._get_hres_z(zi)
        if zz[0] == 0. : zz[0] = 1e-6 # 1e-8 = steps_z(Nz) in f90
        self.zz = zz
        print(" Nz for higher resolution = ", len(zz))

        # redshift bin for P(z,k)
        zpk = np.linspace(0, 2, 140)
        if zpk[0] == 0. : zpk[0] = 1e-6
        self.zpk = zpk
        print(" Nz for matter power spectrum = ", len(zpk))


        super().initialize()

    def get_requirements(self):
        return {"Hubble":  {"z": self.zz},
                "angular_diameter_distance": {"z": self.zz},
                "Pk_interpolator": {"z": self.zpk,
                                    "k_max": 5,
                                    "nonlinear": False,
                                    "hubble_units": False,
                                    "k_hunit": False,
                                    "vars_pairs": [["delta_nonu", "delta_nonu"]]},
                "H0": None, "omnuh2": None, "ns":None, "omegam":None, "sigma8":None,
                "ombh2":None, "omch2":None, "As":None, "cosmomc_theta":None}

    def _get_data(self):
        return self.delNcat, self.delN2Dcat

    def _get_om(self):
        return (self.theory.get_param("omch2") + self.theory.get_param("ombh2") + self.theory.get_param("omnuh2"))/((self.theory.get_param("H0")/100.0)**2)

    def _get_Hz(self, z):
        return self.theory.get_Hubble(z)

    def _get_Ez(self, z):
        return self.theory.get_Hubble(z)/self.theory.get_param("H0")

    def _get_DAz(self, z):
        return self.theory.get_angular_diameter_distance(z)

    def _get_hres_z(self, zi):
        # bins in redshifts are defined with higher resolution for z < 0.2
        hr = 0.2
        if zi < hr :
            dzi = 1e-3
        else:
            dzi = 1e-2
        hres_z = zi + dzi
        return hres_z

    def _get_dndlnm(self, z, pk_intp, **kwargs):

        h = self.theory.get_param("H0")/100.0
        Ez = self._get_Ez(z)
        om = self._get_om()
        rhom0 = rhocrit0*om
        marr = self.marr

        k = np.logspace(-4, np.log10(5), 200, endpoint=False)
        zpk = self.zpk
        pks0 = pk_intp.P(zpk, k)

        def pks_zbins(newz):
            i = 0
            newpks = np.zeros((len(newz),len(k)))
            for i in range(k.size):
                tck = interpolate.splrep(zpk, pks0[:,i])
                newpks[:,i] = interpolate.splev(newz, tck)
            return newpks
        pks = pks_zbins(z)

        pks *= h**3.
        kh = k/h

        def radius(M):
            return (0.75*M/pi/rhom0)**(1./3.)

        def win(x):
            return 3.*(np.sin(x) - x*np.cos(x))/(x**3.)

        def win_prime(x):
            return 3.*np.sin(x)/(x**2.) - 9.*(np.sin(x) - x*np.cos(x))/(x**4.)

        def sigma_sq(R, k):
            integral = np.ones((len(k), len(marr), len(z)))
            i = 0
            for i in range(k.size):
                integral[i,:,:] = np.array((k[i]**2.)*pks[:,i]*(win(k[i]*R)**2.))
            return integrate.simps(integral, k, axis=0)/(2.*pi**2.)

        def sigma_sq_prime(R, k):
            integral = np.ones((len(k), len(marr), len(z)))
            i = 0
            for i in range(k.size):
                integral[i,:,:] = np.array((k[i]**2.)*pks[:,i]*2.*k[i]*win(k[i]*R)*win_prime(k[i]*R))
            return integrate.simps(integral, k, axis=0)/(2.*pi**2.)

        def tinker(sgm, z):

            total = 9

            delta  = np.zeros(total)
            par_aa = np.zeros(total)
            par_a  = np.zeros(total)
            par_b  = np.zeros(total)
            par_c  = np.zeros(total)
            der_aa = np.zeros(total)
            der_a  = np.zeros(total)
            der_b  = np.zeros(total)
            der_c  = np.zeros(total)

            delta[0] = 200
            delta[1] = 300
            delta[2] = 400
            delta[3] = 600
            delta[4] = 800
            delta[5] = 1200
            delta[6] = 1600
            delta[7] = 2400
            delta[8] = 3200

            par_aa[0] = 0.186
            par_aa[1] = 0.200
            par_aa[2] = 0.212
            par_aa[3] = 0.218
            par_aa[4] = 0.248
            par_aa[5] = 0.255
            par_aa[6] = 0.260
            par_aa[7] = 0.260
            par_aa[8] = 0.260

            par_a[0] = 1.47
            par_a[1] = 1.52
            par_a[2] = 1.56
            par_a[3] = 1.61
            par_a[4] = 1.87
            par_a[5] = 2.13
            par_a[6] = 2.30
            par_a[7] = 2.53
            par_a[8] = 2.66

            par_b[0] = 2.57
            par_b[1] = 2.25
            par_b[2] = 2.05
            par_b[3] = 1.87
            par_b[4] = 1.59
            par_b[5] = 1.51
            par_b[6] = 1.46
            par_b[7] = 1.44
            par_b[8] = 1.41

            par_c[0] = 1.19
            par_c[1] = 1.27
            par_c[2] = 1.34
            par_c[3] = 1.45
            par_c[4] = 1.58
            par_c[5] = 1.80
            par_c[6] = 1.97
            par_c[7] = 2.24
            par_c[8] = 2.44

            der_aa[0] = 0.00
            der_aa[1] = 0.50
            der_aa[2] = -1.56
            der_aa[3] = 3.05
            der_aa[4] = -2.95
            der_aa[5] = 1.07
            der_aa[6] = -0.71
            der_aa[7] = 0.21
            der_aa[8] = 0.00

            der_a[0] = 0.00
            der_a[1] = 1.19
            der_a[2] = -6.34
            der_a[3] = 21.36
            der_a[4] = -10.95
            der_a[5] = 2.59
            der_a[6] = -0.85
            der_a[7] = -2.07
            der_a[8] = 0.00

            der_b[0] = 0.00
            der_b[1] = -1.08
            der_b[2] = 12.61
            der_b[3] = -20.96
            der_b[4] = 24.08
            der_b[5] = -6.64
            der_b[6] = 3.84
            der_b[7] = -2.09
            der_b[8] = 0.00

            der_c[0] = 0.00
            der_c[1] = 0.94
            der_c[2] = -0.43
            der_c[3] = 4.61
            der_c[4] = 0.01
            der_c[5] = 1.21
            der_c[6] = 1.43
            der_c[7] = 0.33
            der_c[8] = 0.00

            delta = np.log10(delta)

            dso = 500.
            omz = om*((1. + z)**3.)/(Ez**2.)
            dsoz = dso/omz

            par1 = splintnr(delta, par_aa, der_aa, total, np.log10(dsoz))
            par2 = splintnr(delta, par_a, der_a, total, np.log10(dsoz))
            par3 = splintnr(delta, par_b, der_b, total, np.log10(dsoz))
            par4 = splintnr(delta, par_c, der_c, total, np.log10(dsoz))

            alpha = 10.**(-((0.75/np.log10(dsoz/75.))**1.2))
            A     = par1*((1. + z)**(-0.14))
            a     = par2*((1. + z)**(-0.06))
            b     = par3*((1. + z)**(-alpha))
            c     = par4*np.ones(z.size)

            return A * (1. + (sgm/b)**(-a)) * np.exp(-c/(sgm**2.))

        dRdM = radius(np.exp(marr))/(3.*np.exp(marr))
        dRdM = dRdM[:,None]
        R = radius(np.exp(marr))[:,None]
        sigma = sigma_sq(R, kh)**0.5
        sigma_prime = sigma_sq_prime(R, kh)

        return -rhom0 * tinker(sigma, z) * dRdM * sigma_prime/(2.*sigma**2.)

    def _get_dVdzdO(self, z):

        h = self.theory.get_param("H0") / 100.0
        DAz = self._get_DAz(z)
        Hz = self._get_Hz(z)
        dVdzdO = (c_ms/1e3)*(((1. + z)*DAz)**2.)/Hz

        return dVdzdO * h**3.

    def _get_integrated(self, pk_intp, **kwargs):

        marr = np.exp(self.marr)
        dlnm = self.dlnm
        lnmmin = self.lnmmin
        zarr = self.zarr
        zz = self.zz

        Nq = self.Nq
        qarr = self.qarr
        dlogq = self.dlogq
        qcut = self.qcut

        dVdzdO = self._get_dVdzdO(zz)
        dndlnm = self._get_dndlnm(zz, pk_intp, **kwargs)
        y500 = self._get_y500(marr, zz, **kwargs)
        theta500 = self._get_theta500(marr, zz, **kwargs)

        surveydeg2 = self.surveydeg2
        intgr = dndlnm * dVdzdO * surveydeg2
        intgr = intgr.T

        nzarr = np.linspace(0, 1.1, 12)

        if self.choose_dim == '1D':

            c = self._get_completeness(marr, zz, y500, theta500, **kwargs)

            delN = np.zeros(len(zarr))
            i = 0
            for i in range(len(zarr)):
                test = np.abs(zz - nzarr[i])
                i1 = np.argmin(test)
                test = np.abs(zz - nzarr[i+1])
                i2 = np.argmin(test)
                zs = np.arange(i1, i2)

                sum = 0.
                sumzs = np.zeros(len(zz))
                ii = 0
                for ii in zs:
                    j = 0
                    for j in range(len(marr)):
                        sumzs[ii] += 0.5*(intgr[ii,j]*c[ii,j] + intgr[ii+1,j]*c[ii+1,j])*dlnm
                    sum += sumzs[ii]*(zz[ii+1] - zz[ii])

                delN[i] = sum
                print(i, delN[i])

            print("\r Total predicted N = ", delN.sum())
            res = delN

        else:

            cc = self._get_completeness2D(marr, zz, y500, theta500, **kwargs)

            delN2D = np.zeros((len(zarr), Nq+1))
            kk = 0
            for kk in range(Nq+1):
                i = 0
                for i in range(len(zarr)):
                    test = np.abs(zz - nzarr[i])
                    i1 = np.argmin(test)
                    test = np.abs(zz - nzarr[i+1])
                    i2 = np.argmin(test)
                    zs = np.arange(i1, i2)
                    #print(i1, i2)

                    sum = 0.
                    sumzs = np.zeros((len(zz), Nq+1))
                    ii = 0
                    for ii in zs:
                        j = 0
                        for j in range(len(marr)):
                            sumzs[ii,kk] += 0.5*(intgr[ii,j]*cc[ii,j,kk] + intgr[ii+1,j]*cc[ii+1,j,kk])*dlnm

                        sum += sumzs[ii,kk]*(zz[ii+1] - zz[ii])
                    delN2D[i,kk] = sum
                print(kk, delN2D[:,kk].sum())
            print("\r Total predicted 2D N = ", delN2D.sum())

            i = 0
            for i in range(len(zarr)-1):
                print(i, delN2D[i,:].sum())
            res = delN2D

        return res

    def _get_theory(self, pk_intp, **kwargs):

        start = t.time()

        res = self._get_integrated(pk_intp, **kwargs)

        elapsed = t.time() - start
        print("\r ::: theory N calculation took %.1f seconds" %elapsed)

        return res


    # y-m scaling relation for completeness
    def _get_theta500(self, m, z, **params_values_dict):

        bias = params_values_dict["bias_sz"]
        thetastar = 6.997
        alpha_theta = 1./3.

        H0 = self.theory.get_param("H0")
        h = self.theory.get_param("H0") / 100.0
        Ez = self._get_Ez(z)
        DAz = self._get_DAz(z)*h

        m = m[:,None]
        mb = m * bias
        ttstar = thetastar * (H0/70.)**(-2./3.)

        return ttstar*(mb/3.e14*(100./H0))**alpha_theta * Ez**(-2./3.) * (100.*DAz/500/H0)**(-1.)

    def _get_y500(self, m, z, **params_values_dict):

        bias = params_values_dict["bias_sz"]
        logystar = params_values_dict["ystar_sz"]
        alpha = params_values_dict["alpha_sz"]
        beta = params_values_dict["beta_sz"]

        ystar = (10.**logystar)/(2.**alpha)*0.00472724

        H0 = self.theory.get_param("H0")
        h = self.theory.get_param("H0") / 100.0
        Ez = self._get_Ez(z)
        DAz = self._get_DAz(z)*h

        m = m[:,None]
        mb = m * bias
        yystar = ystar * (H0/70.)**(alpha - 2.)

        return yystar*(mb/3.e14*(100./H0))**alpha * Ez**beta * (100.*DAz/500./H0)**(-2.)

    # completeness
    def _get_completeness(self, marr, zarr, y500, theta500, **params_values_dict):

        scatter = params_values_dict["scatter_sz"]
        qcut = self.qcut
        thetas = self.thetas
        ylims = self.ylims
        skyfracs = self.skyfracs
        fsky = skyfracs.sum()
        dim = self.choose_dim

        lnymin = -11.5     #ln(1e-10) = -23
        lnymax = 10.       #ln(1e-2) = -4.6
        dlny = 0.05
        Ny = m.floor((lnymax - lnymin)/dlny) - 1

        yylims = []
        yy = []
        lnyy = []
        dyy = []
        lny = lnymin
        i = 0
        for i in range(Ny):
            yy0 = np.exp(lny)
            erfunc = get_erf(yy0, ylims, qcut)
            yylims.append(np.dot(erfunc.T, skyfracs))

            yy.append(yy0)
            lnyy.append(lny)
            dyy.append(np.exp(lny + dlny) - np.exp(lny))
            lny += dlny

        yylims = np.asarray(yylims)
        yy = np.asarray(yy)
        lnyy = np.asarray(lnyy)
        dyy = np.asarray(dyy)

        a_pool = multiprocessing.Pool()
        completeness = a_pool.map(partial(get_comp_zarr_plc,
                                            Nm=len(marr),
                                            dim=dim,
                                            thetas=thetas,
                                            ylims=ylims,
                                            skyfracs=skyfracs,
                                            y500=y500,
                                            theta500=theta500,
                                            qcut=qcut,
                                            qqarr=None,
                                            lnyy=lnyy,
                                            dyy=dyy,
                                            yy=yy,
                                            yylims=yylims,
                                            scatter=scatter),range(len(zarr)))
        a_pool.close()
        comp = np.asarray(completeness)
        assert np.all(np.isfinite(comp))
        comp[comp < 0.] = 0.
        comp[comp > fsky] = fsky

        return comp


    def _get_completeness2D(self, marr, zarr, y500, theta500, **params_values_dict):

        scatter = params_values_dict["scatter_sz"]
        qcut = self.qcut
        thetas = self.thetas
        skyfracs = self.skyfracs
        ylims = self.ylims
        fsky = skyfracs.sum()
        dim = self.choose_dim

        Nq = self.Nq
        qarr = self.qarr
        dlogq = self.dlogq

        k = 0
        qqarr = []
        qmin = qarr[0] - dlogq/2.
        for k in range(Nq+2):
            qqarr.append(10.**qmin)
            qmin += dlogq
        qqarr = np.asarray(qqarr)
        qqarr[0] = qcut

        if scatter == 0:

            start1 = t.time()

            a_pool = multiprocessing.Pool()
            completeness = a_pool.map(partial(get_comp_zarr_plc,
                                                Nm=len(marr),
                                                dim=dim,
                                                thetas=thetas,
                                                ylims=ylims,
                                                skyfracs=skyfracs,
                                                y500=y500,
                                                theta500=theta500,
                                                qcut=qcut,
                                                qqarr=qqarr,
                                                lnyy=None,
                                                dyy=None,
                                                yy=None,
                                                yylims=None,
                                                scatter=scatter),range(len(zarr)))
        else:

            start0 = t.time()

            lnymin = -11.5     #ln(1e-10) = -23
            lnymax = 10.       #ln(1e-2) = -4.6
            dlny = 0.05
            Ny = m.floor((lnymax - lnymin)/dlny) - 1

            yy = []
            lnyy = []
            dyy = []
            lny = lnymin
            i = 0
            for i in range(Ny):
                yy0 = np.exp(lny)
                yy.append(yy0)
                lnyy.append(lny)
                dyy.append(np.exp(lny+dlny) - np.exp(lny))
                lny += dlny

            yy = np.asarray(yy)
            lnyy = np.asarray(lnyy)
            dyy = np.asarray(dyy)

            b_pool = multiprocessing.Pool()
            yylims = b_pool.map(partial(get_comp_yarr_plc2D,
                                                qqarr=qqarr,
                                                ylims=ylims,
                                                yy=yy,
                                                skyfracs=skyfracs),range(Ny))

            b_pool.close()

            yylims = np.asarray(yylims)

            elapsed0 = t.time() - start0
            print("\r ::: here 1st pool took %.1f seconds" %elapsed0)

            start1 = t.time()

            a_pool = multiprocessing.Pool()
            completeness = a_pool.map(partial(get_comp_zarr_plc,
                                                Nm=len(marr),
                                                dim=dim,
                                                thetas=thetas,
                                                ylims=ylims,
                                                skyfracs=skyfracs,
                                                y500=y500,
                                                theta500=theta500,
                                                qcut=None,
                                                qqarr=None,
                                                lnyy=lnyy,
                                                dyy=dyy,
                                                yy=yy,
                                                yylims=yylims,
                                                scatter=scatter),range(len(zarr)))
        a_pool.close()
        comp = np.asarray(completeness)
        assert np.all(np.isfinite(comp))
        comp[comp < 0.] = 0.
        comp[comp > fsky] = fsky

        elapsed1 = t.time() - start1
        print("\r ::: here 2nd pool took %.1f seconds" %elapsed1)

        return comp


def splintnr(xa, ya, y2a, n, xx):
    i = 0
    res = []
    for i in range(len(xx)):
        x = xx[i]
        klo = 1
        khi = n
        while khi - klo > 1 :
            k = int((khi + klo)/2.)
            if xa[k] >= x :
                khi = k
            else:
                klo = k
        else:
            h = xa[khi] - xa[klo]
            a = (xa[khi] - x)/h
            b = (x - xa[klo])/h
            y = a*ya[klo] + b*ya[khi] + ( (a**3. - a)*y2a[klo] + (b**3. - b)*y2a[khi]) * (h**2.)/6.
        res.append(y)
    return np.asarray(res)

def get_comp_yarr_plc2D(y_index, qqarr, ylims, yy, skyfracs):

    y = yy[y_index]

    a0 = get_erf(y, ylims, qqarr[0])
    a1 = get_erf(y, ylims, qqarr[1])
    a2 = get_erf(y, ylims, qqarr[2])
    a3 = get_erf(y, ylims, qqarr[3])
    a4 = get_erf(y, ylims, qqarr[4])

    cc = np.array((a0*(1. - a1), a0*a1*(1. - a2), a0*a2*(1. - a3), a0*a3*(1. - a4), a0*a4))
    yylims = np.dot(cc.transpose(0,2,1), skyfracs)
    assert np.all(np.isfinite(yylims))
    return yylims

def get_comp_zarr_plc(index_z, Nm, dim, thetas, ylims, skyfracs, y500, theta500, qcut, qqarr, lnyy, dyy, yy, yylims, scatter):
    Nthetas = len(thetas)
    min_thetas = thetas.min()
    max_thetas = thetas.max()
    dif_theta = np.zeros(Nthetas)
    th0 = theta500.T
    y0 = y500.T
    mu = np.log(y0)

    res = []
    i = 0
    for i in range(Nm):
        if th0[index_z,i] > max_thetas:
            l1 = Nthetas - 1
            l2 = Nthetas - 2
            th1 = thetas[l1]
            th2 = thetas[l2]
        elif th0[index_z,i] < min_thetas:
            l1 = 0
            l2 = 1
            th1 = thetas[l1]
            th2 = thetas[l2]
        else:
            dif_theta = np.abs(thetas - th0[index_z,i])
            l1 = np.argmin(dif_theta)
            th1 = thetas[l1]
            l2 = l1 + 1
            if th1 > th0[index_z,i] : l2 = l1 - 1
            th2 = thetas[l2]

        if dim == "1D":
            if scatter == 0:
                y1 = ylims[:,l1]
                y2 = ylims[:,l2]
                y = y1 + (y2 - y1)/(th2 - th1)*(th0[index_z, i] - th1)
                arg = get_erf(y0[index_z, i], y, qcut)
                res.append(np.dot(arg, skyfracs))
            else:
                fac = 1./np.sqrt(2.*pi*scatter**2)
                y1 = yylims[:,l1]
                y2 = yylims[:,l2]
                y = y1 + (y2 - y1)/(th2 - th1)*(th0[index_z, i] - th1)
                y3 = y[:-1]
                y4 = y[1:]
                arg3 = (lnyy[:-1] - mu[index_z, i])/(np.sqrt(2.)*scatter)
                arg4 = (lnyy[1:] - mu[index_z, i])/(np.sqrt(2.)*scatter)
                yy3 = yy[:-1]
                yy4 = yy[1:]
                py = fac*(y3/yy3*np.exp(-arg3**2.) + y4/yy4*np.exp(-arg4**2.))*0.5
                res.append(np.dot(py, dyy[:-1]))
        else:
            if scatter == 0:
                y1 = ylims[:,l1]
                y2 = ylims[:,l2]
                y = y1 + (y2 - y1)/(th2 - th1)*(th0[index_z, i] - th1)
                a0 = get_erf(y0[index_z,i], y, qqarr[0])
                a1 = get_erf(y0[index_z,i], y, qqarr[1])
                a2 = get_erf(y0[index_z,i], y, qqarr[2])
                a3 = get_erf(y0[index_z,i], y, qqarr[3])
                a4 = get_erf(y0[index_z,i], y, qqarr[4])

                cc = np.array((a0*(1. - a1), a0*a1*(1. - a2), a0*a2*(1. - a3), a0*a3*(1. - a4), a0*a4))
                res.append(np.dot(cc, skyfracs))

            else:
                fac = 1./np.sqrt(2.*pi*scatter**2)
                y1 = yylims[:,:,l1]
                y2 = yylims[:,:,l2]
                y = y1 + (y2 - y1)/(th2 - th1)*(th0[index_z, i] - th1)
                y3 = y[:-1,:].T
                y4 = y[1:,:].T
                arg3 = (lnyy[:-1] - mu[index_z, i])/(np.sqrt(2.)*scatter)
                arg4 = (lnyy[1:] - mu[index_z, i])/(np.sqrt(2.)*scatter)
                yy3 = yy[:-1]
                yy4 = yy[1:]
                py = fac*(y3/yy3*np.exp(-arg3**2.) + y4/yy4*np.exp(-arg4**2.))*0.5
                res.append(np.dot(py, dyy[:-1]))
    return res