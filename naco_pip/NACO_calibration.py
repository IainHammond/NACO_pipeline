#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Apr  6 16:01:17 2020

@author: lewis
"""
__author__ = 'Lewis Picker'
__all__ = ['find_shadow_list', 'raw_dataset', 'find_nearest', 'find_AGPM_list']
import pdb
import numpy as np
import pyprind
import os
import random
import matplotlib as mpl
mpl.use('Agg') #show option for plot is unavaliable with this option, set specifically to save plots on m3 
from matplotlib import pyplot as plt
from numpy import isclose
from vip_hci.fits import open_fits, write_fits
from vip_hci.preproc import frame_crop, cube_crop_frames, frame_shift,\
cube_subtract_sky_pca, cube_correct_nan, cube_fix_badpix_isolated,cube_fix_badpix_clump,\
cube_recenter_2dfit
from vip_hci.var import frame_center, get_annulus_segments, frame_filter_lowpass,\
mask_circle, dist, fit_2dgaussian, frame_filter_highpass, get_circle
from vip_hci.metrics import detection, normalize_psf
from vip_hci.conf import time_ini, time_fin, timing
from hciplot import plot_frames
from naco_pip import fits_info
from skimage.feature import register_translation
from photutils import CircularAperture, aperture_photometry

#example on how to define the objects
#test = raw_dataset('/home/lewis/Documents/Exoplanets/data_sets/HD179218/Tests/', '/home/lewis/Documents/Exoplanets/data_sets/HD179218/Debug/')


def find_shadow_list(self, file_list, threshold = 0, verbose = True, debug = False, plot = None):
        """
        In coro NACO data there is a lyot stop causeing a shadow on the detector
        this method will return the radius and cetral position of the circular shadow
        """

        cube = open_fits(self.inpath + file_list[0])
        nz, ny, nx = cube.shape
        median_frame = np.median(cube, axis = 0)
        median_frame = frame_filter_lowpass(median_frame, median_size = 7, mode = 'median')       
        median_frame = frame_filter_lowpass(median_frame, mode = 'gauss',fwhm_size = 5)
        ycom,xcom = np.unravel_index(np.argmax(median_frame), median_frame.shape)#location of AGPM
        if debug: 
            write_fits(self.outpath + 'shadow_median_frame', median_frame)

        shadow = np.where(median_frame >threshold, 1, 0) #lyot shadow
        #create simmilar shadow centred at the origin
        area = sum(sum(shadow))
        r = np.sqrt(area/np.pi)
        tmp = np.zeros([ny,nx])
        tmp = mask_circle(tmp,radius = r, fillwith = 1)
        tmp = frame_shift(tmp, ycom - ny/2 ,xcom - nx/2 )
        #measure translation 
        shift_yx, _, _ = register_translation(tmp, shadow,
                                      upsample_factor= 100)
        #express as a coordinate
        y, x = shift_yx
        cy = np.round(ycom-y)
        cx = np.round(xcom-x)
        if debug:
            pdb.set_trace()
        if verbose:
            print('The centre of the shadow is','cy = ',y,'cx = ',cx)
        if plot == 'show':
            plot_frames((median_frame, shadow, tmp))
        if plot == 'save': 
            plot_frames((median_frame, shadow, tmp), save = self.outpath + 'shadow_fit')
            
        return cy, cx, r
    
def find_AGPM_list(self, path , verbose = True, debug = False):
        """
        This method will find the location of the AGPM
        it gives a rough approxiamtion of the stars location
        Need to supply the path to the cube
        """
        cube = open_fits(path)
        nz, ny, nx = cube.shape
        median_frame = np.median(cube, axis = 0)
        #filter for the brightest source 
        median_frame = frame_filter_lowpass(median_frame, median_size = 7, mode = 'median')       
        median_frame = frame_filter_lowpass(median_frame, mode = 'gauss',fwhm_size = 5)
        #obtain location of the bright source
        ycom,xcom = np.unravel_index(np.argmax(median_frame), median_frame.shape)
        if verbose:
            print('The location of the AGPM is','ycom =',ycom,'xcom =', xcom)
        if debug:
            pdb.set_trace
        return [ycom, xcom]

    
def find_nearest(array, value, output='index', constraint=None):
    """
    Function to find the index, and optionally the value, of an array's closest element to a certain value.
    Possible outputs: 'index','value','both'
    Possible constraints: 'ceil', 'floor', None ("ceil" will return the closest element with a value greater than 'value', "floor" the opposite)
    """
    if type(array) is np.ndarray:
        pass
    elif type(array) is list:
        array = np.array(array)
    else:
        raise ValueError("Input type for array should be np.ndarray or list.")

    idx = (np.abs(array-value)).argmin()
    if type == 'ceil' and array[idx]-value < 0:
        idx+=1
    elif type == 'floor' and value-array[idx] < 0:
        idx-=1

    if output=='index': return idx
    elif output=='value': return array[idx] 
    else: return array[idx], idx

class raw_dataset():  #potentially change dico to a path to the writen list
    """
    In order to successfully run the pipeline you must run the methods in following order:
        self.dark_subtraction()
        self.flat_feild_correction()
        self.correct_nan()
        self.correct_bad_pixels()
        self.first_frames_removal()
        self.get_stellar_psf()
        self.subract_sky()
    This will prevent any undefined variables. 
    """
    
    def __init__(self, inpath, outpath, final_sz = None, coro = True):
        self.inpath = inpath
        self.outpath = outpath        
        self.final_sz = final_sz
        sci_list = []
        # get the common size (crop size)
        with open(self.inpath+"sci_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                sci_list.append(line.split('\n')[0])
        nx = open_fits(self.inpath + sci_list[0]).shape[2]
        self.com_sz = np.array([int(nx - 1)])
        write_fits(self.outpath + 'common_sz', self.com_sz)
        #the size of the shadow in NACO data should be constant.
        #will differ for NACO data where the choronograph has been adjusted
        self.shadow_r = 280 
        
        
    def get_final_sz(self, final_sz = None, verbose = True, debug = False):
        """
        Update the corpping size as you wish
        """
        if final_sz is None:
            final_sz_ori = min(2*self.agpm_pos[0]-1,2*self.agpm_pos[1]-1,2*\
                               (self.com_sz-self.agpm_pos[0])-1,2*\
                               (self.com_sz-self.agpm_pos[1])-1, int(2*self.shadow_r))
        else:
            final_sz_ori = min(2*self.agpm_pos[0]-1,2*self.agpm_pos[1]-1,\
                               2*(self.com_sz-self.agpm_pos[0])-1,\
                               2*(self.com_sz-self.agpm_pos[1])-1,\
                               int(2*self.shadow_r), final_sz)
        if final_sz_ori%2 == 0:
            final_sz_ori -= 1
        final_sz = final_sz_ori
        if verbose:
            print('the final crop size is ', final_sz)
        if debug:
            pdb.set_trace()
        return final_sz



    def dark_subtract(self, verbose = True, debug = False, plot = None, remove = False):
        """
        Dark subtraction of the fits using PCA
        plot options: 'save', 'show', None
        """
        sci_list = []
        with open(self.inpath +"sci_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                sci_list.append(line.split('\n')[0])

        sky_list = []
        with open(self.inpath +"sky_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                sky_list.append(line.split('\n')[0])
        
        unsat_list = []
        with open(self.inpath +"unsat_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                unsat_list.append(line.split('\n')[0])

        unsat_dark_list = []
        with open(self.inpath +"unsat_dark_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                unsat_dark_list.append(line.split('\n')[0])

        flat_list = []
        with open(self.inpath +"flat_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                flat_list.append(line.split('\n')[0])

        flat_dark_list = []
        with open(self.inpath +"flat_dark_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                flat_dark_list.append(line.split('\n')[0])

        sci_dark_list = []
        with open(self.inpath +"sci_dark_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                sci_dark_list.append(line.split('\n')[0])
                
        if os.path.isfile(self.inpath + sci_list[-1]) == False:
            raise NameError('Missing .fits. Double check the contents of the input path') 
          
        self.com_sz = int(open_fits(self.outpath + 'common_sz')[0])
    
        
        pixel_scale = fits_info.pixel_scale
        
        tmp = np.zeros([3, self.com_sz, self.com_sz])
        #cropping the flat dark cubes to com_sz
        for fd, fd_name in enumerate(flat_dark_list):
            tmp_tmp = open_fits(self.inpath+fd_name, header=False, verbose=debug)
            tmp[fd] = frame_crop(tmp_tmp, self.com_sz, force = True , verbose= debug)
        write_fits(self.outpath+'flat_dark_cube.fits', tmp)
        if verbose:
            print('Flat dark cubes have been cropped and saved')
        
        #cropping the SCI dark cubes to com_sz
        for sd, sd_name in enumerate(sci_dark_list):
            tmp_tmp = open_fits(self.inpath+sd_name, header=False, verbose=debug)
            n_dim = tmp_tmp.ndim
            if sd == 0:
                if n_dim == 2:
                    tmp = np.array([frame_crop(tmp_tmp, self.com_sz, 
                                               force = True, verbose=debug)])
                else:
                    tmp = cube_crop_frames(tmp_tmp, self.com_sz, force = True, verbose=debug)
            else:
                if n_dim == 2:
                    tmp = np.append(tmp,[frame_crop(tmp_tmp, self.com_sz, force = True, verbose=debug)],axis=0)
                else:
                    tmp = np.append(tmp,cube_crop_frames(tmp_tmp, self.com_sz, force = True, verbose=debug),axis=0)
        write_fits(self.outpath + 'sci_dark_cube.fits', tmp)
        if verbose:
            print('Sci dark cubes have been cropped and saved')

        #cropping of UNSAT dark frames to the common size or less
        for sd, sd_name in enumerate(unsat_dark_list):
            tmp_tmp = open_fits(self.inpath+sd_name, header=False, verbose=debug)
            n_dim = tmp_tmp.ndim
            
            if sd == 0:
                if n_dim ==2:
                    ny, nx  = tmp_tmp.shape
                    if nx <= self.com_sz:
                        tmp = np.array([frame_crop(tmp_tmp, nx - 1, force = True, verbose = debug)])
                    else:
                        tmp = np.array([frame_crop(tmp_tmp, self.com_sz, force = True, verbose = debug)])
                else:
                    nz , ny, nx = tmp_tmp.shape
                    if nx <= self.com_sz:
                        tmp = cube_crop_frames(tmp_tmp, nx-1, force = True, verbose=debug)
                    else:
                        tmp = cube_crop_frames(tmp_tmp, self.com_sz, force = True, verbose=debug)
            else:
                if n_dim == 2:
                    ny, nx = tmp_tmp.shape
                    if nx <= self.com_sz:
                        tmp = np.append(tmp,[frame_crop(tmp_tmp, nx-1, force = True, verbose=debug)],axis=0)
                    else:
                        tmp = np.append(tmp,[frame_crop(tmp_tmp, self.com_sz, force = True, verbose=debug)],axis=0)
                else:
                    nz, ny, nx = tmp_tmp.shape
                    if nx <= self.com_sz:
                        tmp = np.append(tmp,cube_crop_frames(tmp_tmp, nx - 1, force = True, verbose=debug),axis=0)
                    else:
                        tmp = np.append(tmp,cube_crop_frames(tmp_tmp, self.com_sz, force = True, verbose=debug),axis=0)
        write_fits(self.outpath+'unsat_dark_cube.fits', tmp)
        if verbose:
            print('Unsat dark cubes have been cropped and saved')
        
        #defining the mask for the sky/sci pCA dark subtraction
        cy, cx, self.shadow_r = find_shadow_list(self, sci_list)
        self.shadow_pos = [cy,cx]
        self.agpm_pos = find_AGPM_list(self, self.inpath + sci_list[0])
        mask_AGPM_com = np.ones([self.com_sz,self.com_sz])
        cy,cx = frame_center(mask_AGPM_com)        
        #the shift betwen the AGMP and the centre of the lyot stop
        self.agpm_shadow_shift = [self.agpm_pos[0] - self.shadow_pos[0],self.agpm_pos[1] - self.shadow_pos[1]]

        inner_rad = 3/pixel_scale
        outer_rad =  self.shadow_r*0.8
        
        mask_AGPM_com =  get_annulus_segments(mask_AGPM_com ,inner_rad , outer_rad - inner_rad, mode = 'mask')[0]
        mask_AGPM_com = frame_shift(mask_AGPM_com, self.agpm_pos[0]-cy, self.agpm_pos[1]-cx)
       
        if verbose:
            print('The mask for SCI and SKY cubes have been defined')
        
        mask_AGPM_flat = np.ones([self.com_sz,self.com_sz])
        
        if verbose:
            print('The mask for flatfeilds have been defined')
      
        #now begin the dark subtraction useing PCA
        npc_dark=1 #The ideal number of components to consider in PCA
       
        #coordinate system for pca subraction
        mesh = np.arange(0,self.com_sz,1)
        xv,yv = np.meshgrid(mesh,mesh)
        
        tmp_tmp = np.zeros([len(flat_list),self.com_sz,self.com_sz])
        tmp_tmp_tmp = open_fits(self.outpath+'flat_dark_cube.fits')
        tmp_tmp_tmp_median = np.median(tmp_tmp_tmp, axis = 0)
        #consider the difference in the medium of the frames without the lower left quadrant.
        tmp_tmp_tmp_median = tmp_tmp_tmp_median[np.where(np.logical_or(xv > cx, yv >  cy))]  
        diff = np.zeros([len(flat_list)])
        for fl, flat_name in enumerate(flat_list):
            tmp = open_fits(self.inpath+flat_name, header=False, verbose=debug)
            #PCA works best if the flux is roughly on the same scale hence the difference is subtracted before PCA and added after.
            tmp_tmp[fl] = frame_crop(tmp, self.com_sz, force = True ,verbose=debug)
            tmp_tmp_tmp_tmp = tmp_tmp[fl]
            diff[fl] = np.median(tmp_tmp_tmp_median)-np.median(tmp_tmp_tmp_tmp[np.where(np.logical_or(xv > cx, yv >  cy))])
            tmp_tmp[fl]+=diff[fl]
        if debug:
            print('difference w.r.t dark = ',  diff)
        tmp_tmp_pca = cube_subtract_sky_pca(tmp_tmp, tmp_tmp_tmp,
                                    mask_AGPM_flat, ref_cube=None, ncomp=npc_dark)
        if debug:
            write_fits(self.outpath+'1_crop_flat_cube_diff.fits', tmp_tmp_pca)
        for fl, flat_name in enumerate(flat_list):
            tmp_tmp_pca[fl] = tmp_tmp_pca[fl]-diff[fl]
        write_fits(self.outpath+'1_crop_flat_cube.fits', tmp_tmp_pca)
        if verbose:
            print('Dark has been subtracted from FLAT cubes')
            
        if plot:    
            tmp_tmp_tmp = np.median(tmp_tmp_tmp, axis = 0) #flat_dark median
            tmp_tmp = np.median(tmp_tmp, axis = 0) #flat before subtraction 
            tmp_tmp_pca = np.median(tmp_tmp_pca,axis = 0) #flat after dark subtract
        if plot == 'show':
           plot_frames((tmp_tmp,tmp_tmp_pca,mask_AGPM_flat), vmax = (25000,14000,1), vmin = (-2500,9000,0))
        if plot == 'save':
            plot_frames((tmp_tmp,tmp_tmp_pca,mask_AGPM_flat), vmax = (25000,14000,1), vmin = (-2500,9000,0), save = self.outpath + 'Flat_PCA_dark_subtract')

        
        #PCA dark subtraction of SCI cubes
        tmp_tmp_tmp = open_fits(self.outpath+'sci_dark_cube.fits')
        tmp_tmp_tmp_median = np.median(tmp_tmp_tmp,axis = 0)
        #consider the median within the mask
        tmp_tmp_tmp_median = np.median(tmp_tmp_tmp_median[np.where(mask_AGPM_com)])
        for sc, fits_name in enumerate(sci_list):
            tmp = open_fits(self.inpath+fits_name, header=False, verbose=debug)
            tmp = cube_crop_frames(tmp, self.com_sz, force = True, verbose=debug)
            #PCA works best when the considering the difference
            tmp_median = np.median(tmp,axis = 0)
            tmp_median = tmp_median[np.where(mask_AGPM_com)]
            diff = tmp_tmp_tmp_median - np.median(tmp_median)
            if debug:
                print('difference w.r.t dark =', diff)
            tmp_tmp = cube_subtract_sky_pca(tmp +diff , tmp_tmp_tmp,
                                mask_AGPM_com, ref_cube=None, ncomp=npc_dark)
            if debug:
                write_fits(self.outpath+'1_crop_diff'+fits_name, tmp_tmp)
            write_fits(self.outpath+'1_crop_'+fits_name, tmp_tmp-diff)     
        if verbose:
            print('Dark has been subtracted from SCI cubes')
        if plot: 
            tmp = np.median(tmp, axis = 0)
            tmp_tmp = np.median(tmp_tmp-diff,axis = 0)
        if plot == 'show': 
            plot_frames((tmp,tmp_tmp,mask_AGPM_com),vmax = (25000,25000,1), vmin = (-2500,-2500,0))
        if plot == 'save': 
            plot_frames((tmp,tmp_tmp,mask_AGPM_com),vmax = (25000,25000,1), vmin = (-2500,-2500,0), save = self.outpath + 'SCI_PCA_dark_subtract_')
        
    
        #dark subtract of sky cubes
        tmp_tmp_tmp = open_fits(self.outpath+'sci_dark_cube.fits')
        tmp_tmp_tmp_median = np.median(tmp_tmp_tmp,axis = 0)
        tmp_tmp_tmp_median = np.median(tmp_tmp_tmp_median[np.where(mask_AGPM_com)])
        for sc, fits_name in enumerate(sky_list):
            tmp = open_fits(self.inpath+fits_name, header=False, verbose=debug)
            tmp = cube_crop_frames(tmp, self.com_sz, force = True, verbose=debug)   
            tmp_median = np.median(tmp,axis = 0)
            tmp_median = tmp_median[np.where(mask_AGPM_com)]
            diff = tmp_tmp_tmp_median - np.median(tmp_median)
            if debug:
                   print('difference w.r.t dark = ',  diff)
            tmp_tmp = cube_subtract_sky_pca(tmp +diff, tmp_tmp_tmp,
                                    mask_AGPM_com, ref_cube=None, ncomp=npc_dark)
            if debug:
                write_fits(self.outpath+'1_crop_diff'+fits_name, tmp_tmp)
            write_fits(self.outpath+'1_crop_'+fits_name, tmp_tmp-diff)
        if verbose:
            print('Dark has been subtracted from SKY cubes')
        if plot: 
            tmp = np.median(tmp, axis = 0)
            tmp_tmp = np.median(tmp_tmp-diff,axis = 0)
        if plot == 'show':
            plot_frames((tmp,tmp_tmp,mask_AGPM_com), vmax = (25000,25000,1), vmin = (-2500,-2500,0))
        if plot == 'save':
            plot_frames((tmp,tmp_tmp,mask_AGPM_com), vmax = (25000,25000,1), vmin = (-2500,-2500,0),save = self.outpath + 'SKY_PCA_dark_subtract')

        #dark subtract of unsat cubes
        tmp_tmp_tmp = open_fits(self.outpath+'unsat_dark_cube.fits')
        tmp_tmp_tmp = np.median(tmp_tmp_tmp,axis = 0)
        # no need to crop the unsat frame at the same size as the sci images if they are smaller
        for un, fits_name in enumerate(unsat_list):
            tmp = open_fits(self.inpath+fits_name, header=False)
            if tmp.shape[2] > self.com_sz:
                nx_unsat_crop = self.com_sz
                tmp = cube_crop_frames(tmp, nx_unsat_crop, force = True, verbose = debug)
                tmp_tmp = tmp-tmp_tmp_tmp
            elif tmp.shape[2]%2 == 0:
                nx_unsat_crop = tmp.shape[2]-1
                tmp = cube_crop_frames(tmp, nx_unsat_crop, force = True, verbose = debug)
                tmp_tmp = tmp-tmp_tmp_tmp
            else:
                nx_unsat_crop = tmp.shape[2]
                tmp_tmp = tmp-tmp_tmp_tmp
            write_fits(self.outpath+'1_crop_unsat_'+fits_name, tmp_tmp)
        if verbose:
            print('Dark has been subtracted from UNSAT cubes')
        if plot:
            tmp = np.median(tmp, axis = 0)
            tmp_tmp = np.median(tmp_tmp,axis = 0)
        if plot == 'show':
            plot_frames((tmp_tmp_tmp,tmp,tmp_tmp))
        if plot == 'save':
            plot_frames((tmp_tmp_tmp,tmp,tmp_tmp), save = self.outpath + 'UNSAT_PCA_dark_subtract')


    def flat_field_correction(self, verbose = True, debug = False, plot = None, remove = False):
        """
        Scaling of the Cubes with according the the FLATS, in order to minimise any bias in the pixels
        plot options: 'save', 'show', None. Show or save relevant plots for debugging
        remove options: True, Flase. Cleans file for unused fits
        """
        sci_list = []
        with open(self.inpath +"sci_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                sci_list.append(line.split('\n')[0])

        sky_list = []
        with open(self.inpath +"sky_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                sky_list.append(line.split('\n')[0])

        flat_list = []
        with open(self.inpath +"flat_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                flat_list.append(line.split('\n')[0])

        unsat_list = []
        with open(self.inpath +"unsat_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                unsat_list.append(line.split('\n')[0])
        
        if os.path.isfile(self.outpath + '1_crop_' + sci_list[-1]) == False:
            raise NameError('Missing 1_crop_*.fits. Run: dark_subtract()')  
                
        self.com_sz = int(open_fits(self.outpath + 'common_sz')[0])

        flat_X = []
        flat_X_values = []
        tmp = open_fits(self.outpath+'1_crop_unsat_'+unsat_list[-1],header = False)
        nx_unsat_crop = tmp.shape[2]

        #flat cubes measeured at 3 different airmass 
        for fl, flat_name in enumerate(flat_list):
            tmp, header = open_fits(self.inpath+flat_list[fl], header=True, verbose=debug)
            flat_X.append(header['AIRMASS'])
            if fl == 0:
                flat_X_values.append(header['AIRMASS'])
            else:
                list_occ = [isclose(header['AIRMASS'], x, atol=0.1) for x in flat_X_values]
                if True not in list_occ:
                    flat_X_values.append(header['AIRMASS'])
        if verbose:
            print(flat_X)
        flat_X_values = np.sort(flat_X_values) # !!! VERY IMPORTANT, DO NOT COMMENT, OR IT WILL SCREW EVERYTHING UP!!!
        if verbose:
            print(flat_X_values)
        if verbose:
            print('The airmass values have been sorted into a list')

        # There should be 15 twilight flats in total with NACO; 5 at each airmass. BUG SOMETIMES!
        flat_tmp_cube_1 = np.zeros([5,self.com_sz,self.com_sz])
        flat_tmp_cube_2 = np.zeros([5,self.com_sz,self.com_sz])
        flat_tmp_cube_3 = np.zeros([5,self.com_sz,self.com_sz])
        counter_1 = 0
        counter_2 = 0
        counter_3 = 0

        flat_cube_3X = np.zeros([3,self.com_sz,self.com_sz])

        # TAKE MEDIAN OF each group of 5 frames with SAME AIRMASS
        flat_cube = open_fits(self.outpath+'1_crop_flat_cube.fits', header=False, verbose=debug)
        for fl, self.flat_name in enumerate(flat_list):
            if find_nearest(flat_X_values, flat_X[fl]) == 0:
                flat_tmp_cube_1[counter_1] = flat_cube[fl]
                counter_1 += 1
            elif find_nearest(flat_X_values, flat_X[fl]) == 1:
                flat_tmp_cube_2[counter_2] = flat_cube[fl]
                counter_2 += 1
            elif find_nearest(flat_X_values, flat_X[fl]) == 2:
                flat_tmp_cube_3[counter_3] = flat_cube[fl]
                counter_3 += 1

        flat_cube_3X[0] = np.median(flat_tmp_cube_1,axis=0)
        flat_cube_3X[1] = np.median(flat_tmp_cube_2,axis=0)
        flat_cube_3X[2] = np.median(flat_tmp_cube_3,axis=0)
        if verbose:
            print('The median flat cubes with same airmass have been defined')

        #create master flat field
        med_fl = np.zeros(3)
        gains_all = np.zeros([3,self.com_sz,self.com_sz])
        for ii in range(3):
            med_fl[ii] = np.median(flat_cube_3X[ii])
            gains_all[ii] = flat_cube_3X[ii]/med_fl[ii]
        master_flat_frame = np.median(gains_all, axis=0)
        if nx_unsat_crop < master_flat_frame.shape[1]:
            master_flat_unsat = frame_crop(master_flat_frame,nx_unsat_crop)
        else:
            master_flat_unsat = master_flat_frame

        write_fits(self.outpath+'master_flat_field.fits', master_flat_frame)
        write_fits(self.outpath+'master_flat_field_unsat.fits', master_flat_unsat)
        if verbose:
            print('master flat frames has been saved')
        if plot == 'show': 
            plot_frames((master_flat_frame, master_flat_unsat))

        #scaling of SCI cubes with respects to the master flat
        for sc, fits_name in enumerate(sci_list):
            tmp = open_fits(self.outpath+'1_crop_'+fits_name, verbose=debug)
            tmp_tmp = np.zeros_like(tmp)
            for jj in range(tmp.shape[0]):
                tmp_tmp[jj] = tmp[jj]/master_flat_frame
            write_fits(self.outpath+'2_ff_'+fits_name, tmp_tmp, verbose=debug)
            if remove:
                os.system("rm "+self.outpath+'1_crop_'+fits_name)
        if verbose:
            print('Done scaling SCI frames with respects to ff')
        if plot:
            tmp = np.median(tmp, axis = 0)
            tmp_tmp = np.median(tmp_tmp, axis = 0)
        if plot == 'show':
            plot_frames((master_flat_frame, tmp, tmp_tmp),vmin = (0,0,0),vmax = (2,16000,16000))
        if plot == 'save': 
            plot_frames((master_flat_frame, tmp, tmp_tmp),vmin = (0,0,0),vmax = (2,16000,16000), save = self.outpath + 'SCI_flat_correction')
        
        #scaling of SKY cubes with respects to the master flat
        for sk, fits_name in enumerate(sky_list):
            tmp = open_fits(self.outpath+'1_crop_'+fits_name, verbose=debug)
            tmp_tmp = np.zeros_like(tmp)
            for jj in range(tmp.shape[0]):
                tmp_tmp[jj] = tmp[jj]/master_flat_frame
            write_fits(self.outpath+'2_ff_'+fits_name, tmp_tmp, verbose=debug)
            if remove:
                os.system("rm "+self.outpath+'1_crop_'+fits_name)
        if verbose:
            print('Done scaling SKY frames with respects to ff ')
        if plot:
            tmp = np.median(tmp, axis = 0)
            tmp_tmp = np.median(tmp_tmp, axis = 0)
        if plot == 'show': 
            plot_frames((master_flat_frame, tmp, tmp_tmp),vmin = (0,0,0),vmax = (2,16000,16000))
        if plot == 'save':
            plot_frames((master_flat_frame, tmp, tmp_tmp),vmin = (0,0,0),vmax = (2,16000,16000), save = self.outpath + 'SKY_flat_correction')

        #scaling of UNSAT cubes with respects to the master flat unsat
        for un, fits_name in enumerate(unsat_list):
            tmp = open_fits(self.outpath+'1_crop_unsat_'+fits_name, verbose=debug)
            tmp_tmp = np.zeros_like(tmp)
            for jj in range(tmp.shape[0]):
                tmp_tmp[jj] = tmp[jj]/master_flat_unsat
            write_fits(self.outpath+'2_ff_unsat_'+fits_name, tmp_tmp, verbose=debug)
            if remove:
                os.system("rm "+self.outpath+'1_crop_unsat_'+fits_name)
        if verbose:
            print('Done scaling UNSAT frames with respects to ff')
        if plot:
            tmp = np.median(tmp,axis = 0)
            tmp_tmp = np.median(tmp_tmp, axis = 0)
        if plot == 'show':
            plot_frames((master_flat_unsat,tmp, tmp_tmp),vmin = (0,0,0),vmax = (2,16000,16000))
        if plot == 'save':
            plot_frames((master_flat_unsat,tmp, tmp_tmp),vmin = (0,0,0),vmax = (2,16000,16000), save = self.outpath + 'UNSAT_flat_correction')

    def correct_nan(self, verbose = True, debug = False, plot = None, remove = False):
        """
        Corrects NAN pixels in cubes
        plot options: 'save', 'show', None. Show or save relevant plots for debugging
        remove options: True, Flase. Cleans file for unused fits
        """
        sci_list = []
        with open(self.inpath +"sci_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                sci_list.append(line.split('\n')[0])

        sky_list = []
        with open(self.inpath +"sky_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                sky_list.append(line.split('\n')[0])

        unsat_list = []
        with open(self.inpath +"unsat_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                unsat_list.append(line.split('\n')[0])
        
        if os.path.isfile(self.outpath + '2_ff_' + sci_list[-1]) == False:
            raise NameError('Missing 2_ff_*.fits. Run: flat_field_correction()')  
        
        self.com_sz = int(open_fits(self.outpath + 'common_sz')[0])

        n_sci = len(sci_list)
        n_sky = len(sky_list)

        bar = pyprind.ProgBar(n_sci, stream=1, title='Correcting nan pixels in SCI frames')
        for sc, fits_name in enumerate(sci_list):
            tmp = open_fits(self.outpath+'2_ff_'+fits_name, verbose=debug)
            tmp_tmp = cube_correct_nan(tmp, neighbor_box=3, min_neighbors=3, verbose=debug)
            write_fits(self.outpath+'2_nan_corr_'+fits_name, tmp_tmp, verbose=debug)
            bar.update()
            if remove:
                os.system("rm "+self.outpath+'2_ff_'+fits_name)
        if verbose:
            print('Done corecting NAN pixels in SCI frames')
        if plot:
            tmp = np.median(tmp,axis=0)
            tmp_tmp = np.median(tmp_tmp,axis=0)
        if plot == 'show':
            plot_frames((tmp,tmp_tmp),vmin = (0,0), vmax = (16000,16000))
        if plot == 'save':
            plot_frames((tmp,tmp_tmp),vmin = (0,0), vmax = (16000,16000), save = self.outpath + 'SCI_nan_correction')

        bar = pyprind.ProgBar(n_sky, stream=1, title='Correcting nan pixels in SKY frames')
        for sk, fits_name in enumerate(sky_list):
            tmp = open_fits(self.outpath+'2_ff_'+fits_name, verbose=debug)
            tmp_tmp = cube_correct_nan(tmp, neighbor_box=3, min_neighbors=3, verbose=debug)
            write_fits(self.outpath+'2_nan_corr_'+fits_name, tmp_tmp, verbose=debug)
            bar.update()
            if remove:
                os.system("rm "+self.outpath+'2_ff_'+fits_name)
        if verbose:
            print('Done corecting NAN pixels in SKY frames')
        if plot:
            tmp = np.median(tmp,axis=0)
            tmp_tmp = np.median(tmp_tmp,axis=0)
        if plot == 'show':
            plot_frames((tmp,tmp_tmp),vmin = (0,0), vmax = (16000,16000))
        if plot == 'save':
            plot_frames((tmp,tmp_tmp),vmin = (0,0), vmax = (16000,16000), save = self.outpath + 'SKY_nan_correction')

        for un, fits_name in enumerate(unsat_list):
            tmp = open_fits(self.outpath+'2_ff_unsat_'+fits_name, verbose=debug)
            tmp_tmp = cube_correct_nan(tmp, neighbor_box=3, min_neighbors=3, verbose=debug)
            write_fits(self.outpath+'2_nan_corr_unsat_'+fits_name, tmp_tmp, verbose=debug)
            if remove:
                os.system("rm "+self.outpath+'2_ff_unsat_'+fits_name)
        if verbose:
            print('Done correcting NAN pixels in UNSAT frames')
        if plot:
            tmp = np.median(tmp,axis=0)
            tmp_tmp = np.median(tmp_tmp,axis=0)
        if plot == 'show':
            plot_frames((tmp,tmp_tmp),vmin = (0,0), vmax = (16000,16000))
        if plot == 'save':
            plot_frames((tmp,tmp_tmp),vmin = (0,0), vmax = (16000,16000), save = self.outpath + 'UNSAT_nan_correction')
            
    def correct_bad_pixels(self, verbose = True, debug = False, plot = None, remove = False): 
        """
        Correct bad pixels twice, once for the bad pixels determined from the flatfeilds
        Another correction is needed to correct bad pixels in each frame caused by residuals,
        hot pixels and gamma-rays.
        plot options: 'save', 'show', None. Show or save relevant plots for debugging
        remove options: True, Flase. Cleans file for unused fits
        """
        
        sci_list = []
        with open(self.inpath +"sci_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                sci_list.append(line.split('\n')[0])

        sky_list = []
        with open(self.inpath +"sky_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                sky_list.append(line.split('\n')[0])
                
        unsat_list = []
        with open(self.inpath +"unsat_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                unsat_list.append(line.split('\n')[0])
                
        if os.path.isfile(self.outpath + '2_nan_corr_' + sci_list[-1]) == False:
            raise NameError('Missing 2_nan_corr_*.fits. Run: correct_nan_pixels()')  
            
        self.com_sz = int(open_fits(self.outpath + 'common_sz')[0])
        
        n_sci = len(sci_list)
        ndit_sci = fits_info.ndit_sci
        n_sky = len(sky_list)
        ndit_sky = fits_info.ndit_sky
        
        tmp = open_fits(self.outpath+'2_nan_corr_unsat_'+unsat_list[-1],header = False)
        nx_unsat_crop = tmp.shape[2]
        
        
        master_flat_frame = open_fits(self.outpath+'master_flat_field.fits')
        # Create bpix map
        bpix = np.where(np.abs(master_flat_frame-1.09)>0.41) # i.e. for QE < 0.68 and QE > 1.5
        bpix_map = np.zeros([self.com_sz,self.com_sz])
        bpix_map[bpix] = 1
        if nx_unsat_crop < bpix_map.shape[1]:
            bpix_map_unsat = frame_crop(bpix_map,nx_unsat_crop, force = True)
        else:
            bpix_map_unsat = bpix_map
        
        #number of bad pixels
        nbpix = int(np.sum(bpix_map))
        ntotpix = self.com_sz**2
        
        if verbose:
            print("total number of bpix: ", nbpix)
            print("total number of pixels: ", ntotpix)
            print("=> {}% of bad pixels.".format(100*nbpix/ntotpix))
    
        write_fits(self.outpath+'master_bpix_map.fits', bpix_map)
        write_fits(self.outpath+'master_bpix_map_unsat.fits', bpix_map_unsat)
        if plot == 'show':
            plot_frames((bpix_map, bpix_map_unsat))
        
        #update final crop size
        self.agpm_pos = find_AGPM_list(self, self.outpath + '2_nan_corr_' + sci_list[0])
        self.agpm_pos = [self.agpm_pos[1],self.agpm_pos[0]]
        self.final_sz = self.get_final_sz(self.final_sz)
        write_fits(self.outpath + 'final_sz', np.array([self.final_sz]))
      
        #crop frames to that size
        for sc, fits_name in enumerate(sci_list):
            tmp = open_fits(self.outpath+'2_nan_corr_'+fits_name, verbose= debug)
            tmp_tmp = cube_crop_frames(tmp, self.final_sz, xy=self.agpm_pos, force = True)
            write_fits(self.outpath+'2_crop_'+fits_name, tmp_tmp)
            if remove:
                os.system("rm "+self.outpath+'2_nan_corr_'+fits_name)


        for sk, fits_name in enumerate(sky_list):
            tmp = open_fits(self.outpath+'2_nan_corr_'+fits_name, verbose= debug)
            tmp_tmp = cube_crop_frames(tmp, self.final_sz, xy=self.agpm_pos, force = True)
            write_fits(self.outpath+'2_crop_'+fits_name, tmp_tmp)
            if remove:
                os.system("rm "+self.outpath+'2_nan_corr_'+fits_name)
        if verbose: 
            print('SCI and SKY cubes are cropped to a common size of:',self.final_sz)
            
        # COMPARE BEFORE AND AFTER NAN_CORR + CROP
        if plot:
            old_tmp = open_fits(self.outpath+'2_ff_'+sci_list[0])[-1]
            old_tmp_tmp = open_fits(self.outpath+'2_ff_'+sci_list[1])[-1]
            tmp = open_fits(self.outpath+'2_crop_'+sci_list[0])[-1]
            tmp_tmp = open_fits(self.outpath+'2_crop_'+sci_list[1])[-1]
        if plot == 'show':
            plot_frames((old_tmp, tmp, old_tmp_tmp, tmp_tmp),vmin = (0,0,0,0),vmax =(16000,16000,16000,16000))
        if plot == 'save':
            plot_frames((old_tmp, tmp, old_tmp_tmp, tmp_tmp),vmin = (0,0,0,0),vmax =(16000,16000,16000,16000), save = self.outpath + 'Second_badpx_crop')
            
        # Crop the bpix map in a same way
        bpix_map = frame_crop(bpix_map,self.final_sz,cenxy=self.agpm_pos, force = True)
        write_fits(self.outpath+'master_bpix_map_2ndcrop.fits', bpix_map)
        
        self.agpm_pos = find_AGPM_list(self, self.outpath + '2_crop_' + sci_list[0])
        self.agpm_pos = [self.agpm_pos[1],self.agpm_pos[0]]
        
        
        t0 = time_ini()
        for sc, fits_name in enumerate(sci_list):
            tmp = open_fits(self.outpath +'2_crop_'+fits_name, verbose=debug)
            # first with the bp max defined from the flat field (without protecting radius)
            tmp_tmp = cube_fix_badpix_clump(tmp, bpm_mask=bpix_map)
            write_fits(self.outpath+'2_bpix_corr_'+fits_name, tmp_tmp, verbose=debug)
            timing(t0)
            # second, residual hot pixels
            tmp_tmp = cube_fix_badpix_isolated(tmp_tmp, bpm_mask=None, sigma_clip=8, num_neig=5, 
                                                           size=5, protect_mask=True, frame_by_frame = True,
                                                           radius=10, verbose=debug,
                                                           debug=False)
            #create a bpm for the 2nd correction
            tmp_tmp_tmp = tmp_tmp-tmp
            tmp_tmp_tmp = np.where(tmp_tmp_tmp != 0 ,1,0)
            write_fits(self.outpath+'2_bpix_corr2_'+fits_name, tmp_tmp)
            write_fits(self.outpath+'2_bpix_corr2_map_'+fits_name,tmp_tmp_tmp)
            timing(t0)
            if remove:
                os.system("rm "+self.outpath+'2_crop_'+fits_name)
        if verbose:
            print('Bad pixels corrected in SCI cubes')
        if plot == 'show':
            plot_frames((tmp_tmp_tmp[0],tmp[0],tmp_tmp[0]),vmin=(0,0,0), vmax = (1,16000,16000))
        if plot =='save':
            plot_frames((tmp_tmp_tmp[0],tmp[0],tmp_tmp[0]),vmin=(0,0,0), vmax = (1,16000,16000), save = self.outpath + 'SCI_badpx_corr')
                    
        bpix_map = open_fits(self.outpath+'master_bpix_map_2ndcrop.fits')
        t0 = time_ini()
        for sk, fits_name in enumerate(sky_list):
            tmp = open_fits(self.outpath+'2_crop_'+fits_name, verbose=debug)
            # first with the bp max defined from the flat field (without protecting radius)
            tmp_tmp = cube_fix_badpix_clump(tmp, bpm_mask=bpix_map)
            write_fits(self.outpath+'2_bpix_corr_'+fits_name, tmp_tmp, verbose=debug)
            timing(t0)
            # second, residual hot pixels
            tmp_tmp = cube_fix_badpix_isolated(tmp_tmp, bpm_mask=None, sigma_clip=8, num_neig=5, 
                                                           size=5, protect_mask=True, frame_by_frame = True, 
                                                           radius=10, verbose=debug,
                                                           debug=False)
            #create a bpm for the 2nd correction
            bpm = tmp_tmp-tmp
            bpm = np.where(bpm != 0 ,1,0)
            write_fits(self.outpath+'2_bpix_corr2_'+fits_name, tmp_tmp)
            write_fits(self.outpath+'2_bpix_corr2_map_'+fits_name, bpm)
            timing(t0)
            if remove:
                os.system("rm "+self.outpath +'2_crop_'+fits_name)
        if verbose:
            print('Bad pixels corrected in SKY cubes')
        if plot == 'show':
            plot_frames((tmp_tmp_tmp[0],tmp[0],tmp_tmp[0]),vmin=(0,0,0), vmax = (1,16000,16000))
        if plot == 'save':
            plot_frames((tmp_tmp_tmp[0],tmp[0],tmp_tmp[0]),vmin=(0,0,0), vmax = (1,16000,16000), save = self.outpath + 'SKY_badpx_corr')

    
        bpix_map_unsat = open_fits(self.outpath+'master_bpix_map_unsat.fits')
        t0 = time_ini()
        for un, fits_name in enumerate(unsat_list):
            tmp = open_fits(self.outpath+'2_nan_corr_unsat_'+fits_name, verbose=debug)
            # first with the bp max defined from the flat field (without protecting radius)
            tmp_tmp = cube_fix_badpix_clump(tmp, bpm_mask=bpix_map_unsat)
            write_fits(self.outpath+'2_bpix_corr_unsat_'+fits_name, tmp_tmp)
            timing(t0)
            # second, residual hot pixels
            tmp_tmp = cube_fix_badpix_isolated(tmp_tmp, bpm_mask=None, sigma_clip=8, num_neig=5, 
                                                           size=5, protect_mask=True, frame_by_frame = True, 
                                                           radius=10, verbose=debug,
                                                           debug=False)
            #create a bpm for the 2nd correction
            bpm = tmp_tmp-tmp
            bpm = np.where(bpm != 0 ,1,0)
            write_fits(self.outpath+'2_bpix_corr2_unsat_'+fits_name, tmp_tmp)
            write_fits(self.outpath+'2_bpix_corr2_map_unsat_'+fits_name, bpm)
            timing(t0)
            if remove:
                os.system("rm "+ self.outpath +'2_nan_corr_unsat_'+fits_name)
        if verbose:
            print('Bad pixels corrected in UNSAT cubes')
        if plot == 'show': 
            plot_frames((tmp_tmp_tmp[0],tmp[0],tmp_tmp[0]),vmin=(0,0,0), vmax = (1,16000,16000))
        if plot == 'save':
            plot_frames((tmp_tmp_tmp[0],tmp[0],tmp_tmp[0]),vmin=(0,0,0), vmax = (1,16000,16000), save = self.outpath + 'UNSAT_badpx_corr')
        
        # FIRST CREATE MASTER CUBE FOR SCI
        tmp_tmp_tmp = open_fits(self.outpath+'2_bpix_corr2_'+sci_list[0], verbose=debug)
        n_y = tmp_tmp_tmp.shape[1]
        n_x = tmp_tmp_tmp.shape[2]
        tmp_tmp_tmp = np.zeros([n_sci,n_y,n_x])
        for sc, fits_name in enumerate(sci_list[:1]):
            tmp_tmp_tmp[sc] = open_fits(self.outpath+'2_bpix_corr2_'+fits_name, verbose=debug)[int(random.randrange(min(ndit_sci)))]
        tmp_tmp_tmp = np.median(tmp_tmp_tmp, axis=0)
        write_fits(self.outpath+'TMP_2_master_median_SCI.fits',tmp_tmp_tmp)
        if verbose:
            print('Master cube for SCI has been created')
            
        # THEN CREATE MASTER CUBE FOR SKY
        tmp_tmp_tmp = open_fits(self.outpath+'2_bpix_corr2_'+sky_list[0], verbose=debug)
        n_y = tmp_tmp_tmp.shape[1]
        n_x = tmp_tmp_tmp.shape[2]
        tmp_tmp_tmp = np.zeros([n_sky,n_y,n_x])
        for sk, fits_name in enumerate(sky_list[:1]):
            tmp_tmp_tmp[sk] = open_fits(self.outpath+'2_bpix_corr2_'+fits_name, verbose=debug)[int(random.randrange(min(ndit_sky)))]
        tmp_tmp_tmp = np.median(tmp_tmp_tmp, axis=0)
        write_fits(self.outpath+'TMP_2_master_median_SKY.fits',tmp_tmp_tmp)
        if verbose:
            print('Master cube for SKY has been created')
            
        if plot:
            bpix_map_ori = open_fits(self.outpath+'master_bpix_map_2ndcrop.fits')
            bpix_map_sci_0 = open_fits(self.outpath+'2_bpix_corr2_map_'+sci_list[0])[0]
            bpix_map_sci_1 = open_fits(self.outpath+'2_bpix_corr2_map_'+sci_list[-1])[0]
            bpix_map_sky_0 = open_fits(self.outpath+'2_bpix_corr2_map_'+sky_list[0])[0]
            bpix_map_sky_1 = open_fits(self.outpath+'2_bpix_corr2_map_'+sky_list[-1])[0]
            bpix_map_unsat_0 = open_fits(self.outpath+'2_bpix_corr2_map_unsat_'+unsat_list[0])[0]
            bpix_map_unsat_1 = open_fits(self.outpath+'2_bpix_corr2_map_unsat_'+unsat_list[-1])[0]
            tmpSKY = open_fits(self.outpath+'TMP_2_master_median_SKY.fits')
        
        #COMPARE BEFORE AND AFTER BPIX CORR (without sky subtr)
        if plot:   
            tmp = open_fits(self.outpath+'2_crop_'+sci_list[1])[-1]
            tmp_tmp = open_fits(self.outpath+'2_bpix_corr2_'+sci_list[1])[-1]
            tmp2 = open_fits(self.outpath+'2_crop_'+sky_list[1])[-1]
            tmp_tmp2 = open_fits(self.outpath+'2_bpix_corr2_'+sky_list[1])[-1]
        if plot == 'show':
            plot_frames((bpix_map_ori, bpix_map_sci_0, bpix_map_sci_1,
                    bpix_map_sky_0, bpix_map_sky_1,
                    bpix_map_unsat_0, bpix_map_unsat_1))
            plot_frames((tmp, tmp-tmpSKY, tmp_tmp, tmp_tmp - tmpSKY, tmp2, tmp2-tmpSKY, 
                                                tmp_tmp2, tmp_tmp2 - tmpSKY))
        if plot == 'save': 
             plot_frames((bpix_map_ori, bpix_map_sci_0, bpix_map_sci_1,
                    bpix_map_sky_0, bpix_map_sky_1,
                    bpix_map_unsat_0, bpix_map_unsat_1), save = self.outpath + 'badpx_maps' )
             plot_frames((tmp, tmp-tmpSKY, tmp_tmp, tmp_tmp - tmpSKY, tmp2, tmp2-tmpSKY, 
                                                tmp_tmp2, tmp_tmp2 - tmpSKY), save = self.outpath + 'Badpx_comparison')
            
            
    def first_frames_removal(self, verbose = True, debug = False, plot = None, remove = False):
        """
        Corrects for the inconsistent DIT times within NACO cubes 
        The first few frames are removed and the rest rescaled such that the flux is constant.
        plot options: 'save', 'show', None. Show or save relevant plots for debugging
        remove options: True, False. Cleans file for unused fits
        """
        sci_list = []
        with open(self.inpath +"sci_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                sci_list.append(line.split('\n')[0])
        n_sci = len(sci_list)
        
        sky_list = []
        with open(self.inpath +"sky_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                sky_list.append(line.split('\n')[0])
        n_sky = len(sky_list)
        
        unsat_list = []
        with open(self.inpath +"unsat_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                unsat_list.append(line.split('\n')[0])
                
        if os.path.isfile(self.outpath + '2_bpix_corr2_' + sci_list[-1]) == False:
            raise NameError('Missing 2_bpix_corr2_*.fits. Run: correct_bad_pixels()')
        
        self.final_sz = int(open_fits(self.outpath + 'final_sz')[0])
                
        com_sz = open_fits(self.outpath + '2_bpix_corr2_' +sci_list[0]).shape[2]
        #obtaining the real ndit values of the frames (not that of the headers)
        tmp = np.zeros([n_sci,com_sz,com_sz])
        self.real_ndit_sci = [] #change all to self.
        for sc, fits_name in enumerate(sci_list):
            tmp_tmp = open_fits(self.outpath+'2_bpix_corr2_'+fits_name, verbose=debug)
            tmp[sc] = tmp_tmp[-1]
            self.real_ndit_sci.append(tmp_tmp.shape[0]-1)
        if plot == 'show':
            plot_frames(tmp[-1])
            
        tmp = np.zeros([n_sky,com_sz,com_sz])
        self.real_ndit_sky = []
        for sk, fits_name in enumerate(sky_list):
            tmp_tmp = open_fits(self.outpath+'2_bpix_corr2_'+fits_name, verbose=debug)
            tmp[sk] = tmp_tmp[-1]
            self.real_ndit_sky.append(tmp_tmp.shape[0]-1)
        if plot == 'show':
            plot_frames(tmp[-1])
        
        min_ndit_sci = int(np.amin(self.real_ndit_sci))
        
        #save the real_ndit_sci and sky lists to a text file     
#        with open(self.outpath+"real_ndit_sci_list.txt", "w") as f:
#            for dimension in self.real_ndit_sci:
#                f.write(str(dimension)+'\n')
#                
#        with open(self.outpath+"real_ndit_sky_list.txt", "w") as f:
#            for dimension in self.real_ndit_sky:
#                f.write(str(dimension)+'\n') 
#        write_fits(self.outpath +'real_ndit_sci', np.array(real_ndit_sci))
#        write_fits(self.outpath + 'real_ndit_sky', np.array(self.real_ndit_sky))
        write_fits(self.outpath +'real_ndit_sci_sky',np.array([self.real_ndit_sci,self.real_ndit_sky]))        

        if verbose:
            print( "real_ndit_sky = ", self.real_ndit_sky)
            print( "real_ndit_sci = ", self.real_ndit_sci) 
            print( "Nominal ndit: {}, min ndit when skimming through cubes: {}".format(fits_info.ndit_sci,min_ndit_sci))
        
        #update the final size and subsequesntly the mask
        mask_inner_rad = int(3.0/fits_info.pixel_scale) 
        mask_width =int((self.final_sz/2.)-mask_inner_rad-2)
        
        #measure the flux in sci avoiding the star at the centre (3'' should be enough)
        tmp_fluxes = np.zeros([n_sci,min_ndit_sci])
        bar = pyprind.ProgBar(n_sci, stream=1, title='Estimating flux in SCI frames')
        for sc, fits_name in enumerate(sci_list):
            tmp = open_fits(self.outpath+'2_bpix_corr2_'+fits_name, verbose=debug)
            for ii in range(min_ndit_sci):
                tmp_tmp = get_annulus_segments(tmp[ii], mask_inner_rad, mask_width, mode = 'mask')[0]
                tmp_fluxes[sc,ii]=np.sum(tmp_tmp)
            bar.update()
        tmp_flux_med = np.median(tmp_fluxes, axis=0)
        if verbose: 
            print('total Flux in SCI frames has been measured')  
 
        #create a plot of the median flux in the frames 
        med_flux = np.median(tmp_flux_med)
        std_flux = np.std(tmp_flux_med)
        if verbose:
            print( "median flux: ", med_flux)
            print( "std flux: ", std_flux)
        first_time = True
        for ii in range(min_ndit_sci):
            if tmp_flux_med[ii] > med_flux+2*std_flux or tmp_flux_med[ii] < med_flux-2*std_flux or ii == 0:
                symbol = 'ro'
                label = 'bad'
            else:
                symbol = 'bo'
                label = 'good'
                if first_time:
                    nfr_rm = ii #the ideal number is when the flux is within 3 standar deviations
                    if verbose:
                        print( "The ideal number of frames to remove at the beginning is: ", nfr_rm)
                    first_time = False
            if plot:
                plt.plot(ii, tmp_flux_med[ii]/med_flux,symbol, label = label)
        if plot:
            plt.title("Flux in SCI frames")
            plt.ylabel('Normalised flux')
            plt.xlabel('Frame number')
        if plot == 'save':
            plt.savefig(self.outpath + "Bad_frames.pdf", bbox_inches = 'tight')
        if plot == 'show':
            plt.show()

            
        #update the range of frames that will be cut off.
        for zz in range(len(self.real_ndit_sci)):
            self.real_ndit_sci[zz] = min(self.real_ndit_sci[zz] - nfr_rm, min(fits_info.ndit_sci) - nfr_rm)
        min_ndit_sky = min(self.real_ndit_sky)
        for zz in range(len(self.real_ndit_sky)):
            self.real_ndit_sky[zz] = min_ndit_sky  - nfr_rm
        
        self.new_ndit_sci = min(fits_info.ndit_sci) - nfr_rm
        self.new_ndit_sky = min(fits_info.ndit_sky) - nfr_rm
        self.new_ndit_unsat = min(fits_info.ndit_unsat) - nfr_rm
        
        write_fits(self.outpath + 'new_ndit_sci_sky_unsat', np.array([self.new_ndit_sci,self.new_ndit_sky,self.new_ndit_unsat]) )
  
        if verbose:
            print( "The new number of frames in each SCI cube is: ", self.new_ndit_sci)
            print( "The new number of frames in each SKY cube is: ", self.new_ndit_sky)
            print( "The new number of frames in each UNSAT cube is: ", self.new_ndit_unsat)
        
        angles = open_fits(self.inpath + "derot_angles_uncropped.fits")
        angles_cropped = angles[:,nfr_rm:] #crops each cube of rotation angles file, by keeping all cubes but removing the number of frames at the start
        write_fits(self.outpath + 'derot_angles_cropped.fits',angles_cropped) #need to make attribute 
        
        # Actual cropping of the cubes to remove the first frames, and the last one (median) AND RESCALING IN FLUX
        for sc, fits_name in enumerate(sci_list):
            tmp = open_fits(self.outpath+'2_bpix_corr2_'+fits_name, verbose=debug)
            tmp_tmp = np.zeros([int(self.real_ndit_sci[sc]),tmp.shape[1],tmp.shape[2]])
            for dd in range(nfr_rm,nfr_rm+int(self.real_ndit_sci[sc])):
                tmp_tmp[dd-nfr_rm] = tmp[dd]*np.median(tmp_fluxes[sc])/tmp_fluxes[sc,dd]
                
            write_fits(self.outpath + '3_rmfr_'+fits_name, tmp_tmp)
            
            if remove:
                os.system("rm "+self.outpath+'2_bpix_corr_'+fits_name)
                os.system("rm "+self.outpath+'2_bpix_corr2_'+fits_name)
                os.system("rm "+self.outpath+'2_bpix_corr2_map_'+fits_name)
        if verbose:
            print('The first {} frames were removed and the flux rescaled for SCI cubes'.format(nfr_rm))
            
        # NOW DOUBLE CHECK THAT FLUXES ARE CONSTANT THROUGHOUT THE CUBE        
        tmp_fluxes = np.zeros([n_sci,self.new_ndit_sci])
        bar = pyprind.ProgBar(n_sci, stream=1, title='Estimating flux in SCI frames')
        for sc, fits_name in enumerate(sci_list):
            tmp = open_fits(self.outpath+'3_rmfr_'+fits_name, verbose=debug)
            for ii in range(self.new_ndit_sci):
                tmp_tmp = get_annulus_segments(tmp[ii], mask_inner_rad, mask_width, mode = 'mask')[0]
                tmp_fluxes[sc,ii]=np.sum(tmp_tmp)
            bar.update()
        tmp_flux_med2 = np.median(tmp_fluxes, axis=0)
        
        #reestimating how many frames should be removed at the begining of the cube
        #hint: if done correctly there should be 0
        med_flux = np.median(tmp_flux_med2)
        std_flux = np.std(tmp_flux_med2)
        if verbose:
            print( "median flux: ", med_flux)
            print( "std flux: ", std_flux)
        first_time = True
        for ii in range(min_ndit_sci-nfr_rm):
            if tmp_flux_med2[ii] > med_flux+std_flux or tmp_flux_med[ii] < med_flux-std_flux:
                symbol = 'ro'
                label = "bad"
            else:
                symbol = 'bo'
                label = "good"
            if plot:
                plt.plot(ii, tmp_flux_med2[ii]/np.amax(tmp_flux_med2),symbol,label = label)
        if plot:
            plt.title("FLux in frames 2nd pass")
            plt.xlabel('Frame number')
            plt.ylabel('Flux')
        if plot == 'save':
            plt.savefig(self.outpath+"Bad_frames_2.pdf", bbox_inches = 'tight')
        if plot == 'show':
            plt.show()
        
        
        #FOR SCI
        tmp_fluxes = np.zeros([n_sci,self.new_ndit_sci])
        bar = pyprind.ProgBar(n_sci, stream=1, title='Estimating flux in OBJ frames')
        for sc, fits_name in enumerate(sci_list):
            tmp = open_fits(self.outpath+'3_rmfr_'+fits_name, verbose=debug) ##
            if sc == 0:
                cube_meds = np.zeros([n_sci,tmp.shape[1],tmp.shape[2]])
            cube_meds[sc] = np.median(tmp,axis=0)
            for ii in range(self.new_ndit_sci):
                tmp_tmp = get_annulus_segments(tmp[ii], mask_inner_rad, mask_width, 
                                              mode = 'mask')[0]
                tmp_fluxes[sc,ii]=np.sum(tmp_tmp)
            bar.update()
        tmp_flux_med = np.median(tmp_fluxes, axis=0)
        write_fits(self.outpath+"TMP_med_bef_SKY_subtr.fits",np.median(cube_meds,axis=0)) # USED LATER to identify dust specks
        
        
        # FOR SKY
        tmp_fluxes_sky = np.zeros([n_sky,self.new_ndit_sky])
        bar = pyprind.ProgBar(n_sky, stream=1, title='Estimating flux in SKY frames')
        for sk, fits_name in enumerate(sky_list):
            tmp = open_fits(self.outpath+'2_bpix_corr2_'+fits_name, verbose=debug) ##
            for ii in range(nfr_rm,nfr_rm+self.new_ndit_sky):
                tmp_tmp = get_annulus_segments(tmp[ii], mask_inner_rad, mask_width, 
                                              mode = 'mask')[0]
                tmp_fluxes_sky[sk,ii-nfr_rm]=np.sum(tmp_tmp)
            bar.update()
        tmp_flux_med_sky = np.median(tmp_fluxes_sky, axis=0)

        # COMPARE 
        if plot:
            plt.plot(range(nfr_rm,nfr_rm+self.new_ndit_sci), tmp_flux_med,'bo',label = 'Sci')
            plt.plot(range(nfr_rm,nfr_rm+self.new_ndit_sky), tmp_flux_med_sky,'ro', label = 'Sky')
            plt.plot(range(1,n_sky+1), np.median(tmp_fluxes_sky,axis=1),'yo', label = 'Medain sky')
            plt.xlabel('Frame number')
            plt.ylabel('Flux')
            plt.legend()
        if plot == 'save':
            plt.savefig(self.outpath+"Frame_sky_compare", bbox_inches = 'tight')
        if plot == 'show':
            plt.show()
        
        for sk, fits_name in enumerate(sky_list):
            tmp = open_fits(self.outpath+'2_bpix_corr2_'+fits_name, verbose=debug)
            tmp_tmp = np.zeros([int(self.real_ndit_sky[sk]),tmp.shape[1],tmp.shape[2]])
            for dd in range(nfr_rm,nfr_rm+int(self.real_ndit_sky[sk])):
                tmp_tmp[dd-nfr_rm] = tmp[dd]*np.median(tmp_fluxes_sky[sk,nfr_rm:])/tmp_fluxes_sky[sk,dd-nfr_rm]
                
            write_fits(self.outpath+'3_rmfr_'+fits_name, tmp_tmp)
            if remove:
                os.system("rm "+self.outpath+'2_bpix_corr_'+fits_name)
                os.system("rm "+self.outpath+'2_bpix_corr2_'+fits_name)
                os.system("rm "+self.outpath+'2_bpix_corr2_map_'+fits_name)
                
        tmp_fluxes_sky = np.zeros([n_sky,self.new_ndit_sky])
        bar = pyprind.ProgBar(n_sky, stream=1, title='Estimating flux in SKY frames')
        for sk, fits_name in enumerate(sky_list):
            tmp = open_fits(self.outpath+'3_rmfr_'+fits_name, verbose=debug) ##
            for ii in range(self.new_ndit_sky):
                tmp_tmp = get_annulus_segments(tmp[ii], mask_inner_rad, mask_width, 
                                              mode = 'mask')[0]
                tmp_fluxes_sky[sk,ii]=np.sum(tmp_tmp)
            bar.update()   
        tmp_flux_med_sky = np.median(tmp_fluxes_sky, axis=0)
        
       
        # COMPARE
        if plot:
            plt.plot(range(nfr_rm,nfr_rm+self.new_ndit_sci), tmp_flux_med,'bo', label = 'Sci')
            plt.plot(range(nfr_rm,nfr_rm+self.new_ndit_sky), tmp_flux_med_sky,'ro', label = 'Sky') #tmp_flux_med_sky, 'ro')#
            plt.xlabel('Frame number')
            plt.ylabel('Flux')
            plt.legend()
        if plot == 'save':
            plt.savefig(self.outpath+"Frame_compare_sky.pdf", bbox_inches = 'tight')
        if plot == 'show':     
            plt.show()    
        
        for un, fits_name in enumerate(unsat_list):
            tmp = open_fits(self.outpath+'2_bpix_corr2_unsat_'+fits_name, verbose=debug)
            tmp_tmp = tmp[nfr_rm:-1]
            write_fits(self.outpath+'3_rmfr_unsat_'+fits_name, tmp_tmp)
            if remove:
                os.system("rm "+self.outpath+'2_bpix_corr_unsat_'+fits_name)
                os.system("rm "+self.outpath+'2_bpix_corr2_unsat_'+fits_name)
                os.system("rm "+self.outpath+'2_bpix_corr2_map_unsat_'+fits_name)
                
    def get_stellar_psf(self, verbose = True, debug = True, plot = None, remove = False): 
        """
        Obtain a PSF model of the star based of the unsat cubes.
        plot options: 'save', 'show', None. Show or save relevant plots for debugging
        remove options: True, Flase. Cleans file for unused fits
        """
        unsat_list = []
        with open(self.inpath +"unsat_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                unsat_list.append(line.split('\n')[0])
        if os.path.isfile(self.outpath + '3_rmfr_unsat_' + unsat_list[-1]) == False:
            raise NameError('Missing 3_rmfr_unsat*.fits. Run: first_frame_removal()')                
                
    
        self.new_ndit_unsat = int(open_fits(self.outpath +'new_ndit_sci_sky_unsat')[2])
                
        unsat_pos = []
        #obtain star positions in the unsat frames
        for fits_name in unsat_list:
            tmp = find_AGPM_list(self, self.outpath + '3_rmfr_unsat_' + fits_name , verbose = True, debug = False)
            unsat_pos.append(tmp)
            
        self.resel_ori = fits_info.wavelength*206265/(fits_info.size_telescope*fits_info.pixel_scale)
        if verbose:
            print('resolution element = ', self.resel_ori)
        
        flux_list = [] 
        #Measure the flux at those positions
        for un, fits_name in enumerate(unsat_list): 
            circ_aper = CircularAperture((unsat_pos[un][1],unsat_pos[un][0]), round(3*self.resel_ori))
            tmp = open_fits(self.outpath + '3_rmfr_unsat_'+ fits_name, verbose = debug)
            tmp = np.median(tmp, axis = 0)
            circ_aper_phot = aperture_photometry(tmp,
                                                    circ_aper, method='exact')
            circ_flux = np.array(circ_aper_phot['aperture_sum'])
            flux_list.append(circ_flux[0])
            
        med_flux = np.median(flux_list)
        std_flux = np.std(flux_list)
        
        good_unsat_list = []
        good_unsat_pos = []
        #define good unsat list where the flux of the stars is within 3 standard devs
        for i,flux in enumerate(flux_list):
            if flux < med_flux + 3*std_flux and flux > med_flux - 3*std_flux:
                good_unsat_list.append(unsat_list[i])   
                good_unsat_pos.append(unsat_pos[i])
                
        unsat_mjd_list = []
        #get times of unsat cubes (modified jullian calander)
        for fname in unsat_list:
            tmp, header = open_fits(self.inpath +fname, header=True,
                                            verbose=debug)
            unsat_mjd_list.append(header['MJD-OBS'])
            
            
        thr_d = (1.0/fits_info.pixel_scale) # threshhold: differene in star pos must be greater than 1 arc sec
        index_dither = [0]
        unique_pos = [unsat_pos[0]]
        counter=1
        for un, pos in enumerate(unsat_pos[1:]):
            new_pos = True
            for i,uni_pos in enumerate(unique_pos):
                if dist(int(pos[1]),int(pos[0]),int(uni_pos[1]),int(uni_pos[0])) < thr_d:
                    index_dither.append(i)
                    new_pos=False
                    break
            if new_pos:
                unique_pos.append(pos)
                index_dither.append(counter)
                counter+=1
        
        all_idx = [i for i in range(len(unsat_list))]
        for un, fits_name in enumerate(unsat_list):
            if fits_name in good_unsat_list: # just consider the good ones
                tmp = open_fits(self.outpath+'3_rmfr_unsat_'+fits_name)
                good_idx = [j for j in all_idx if index_dither[j]!=index_dither[un]] 
                best_idx = find_nearest(unsat_mjd_list[good_idx[0]:good_idx[-1]],unsat_mjd_list[un])
                tmp_sky = np.zeros([len(good_idx),tmp.shape[1],tmp.shape[2]])
                tmp_sky = np.median(open_fits(self.outpath+ '3_rmfr_unsat_'+ unsat_list[good_idx[best_idx]]),axis=0)      
                write_fits(self.outpath+'4_sky_subtr_unsat_'+unsat_list[un], tmp-tmp_sky) 
        if remove:
            for un, fits_name in enumerate(unsat_list):
                os.system("rm "+self.outpath+'3_rmfr_unsat_'+fits_name)
        
        if plot: 
            old_tmp = np.median(open_fits(self.outpath+'4_sky_subtr_unsat_'+unsat_list[0]), axis=0)
            old_tmp_tmp = np.median(open_fits(self.outpath+'4_sky_subtr_unsat_'+unsat_list[-1]), axis=0)
            tmp = np.median(open_fits(self.outpath+'3_rmfr_unsat_'+unsat_list[0]), axis=0)
            tmp_tmp = np.median(open_fits(self.outpath+'3_rmfr_unsat_'+unsat_list[-1]), axis=0)   
        if plot == 'show':   
            plot_frames((old_tmp, tmp, old_tmp_tmp, tmp_tmp))
        if plot == 'save': 
            plot_frames((old_tmp, tmp, old_tmp_tmp, tmp_tmp), save = self.outpath + 'UNSAT_skysubtract')
                    
        crop_sz_tmp = int(6*self.resel_ori)
        crop_sz = int(5*self.resel_ori)
        psf_tmp = np.zeros([len(good_unsat_list)*self.new_ndit_unsat,crop_sz,crop_sz])
        for un, fits_name in enumerate(good_unsat_list):
            tmp = open_fits(self.outpath+'4_sky_subtr_unsat_'+fits_name)
            xy=(good_unsat_pos[un][1],good_unsat_pos[un][0])
            tmp_tmp, tx, ty = cube_crop_frames(tmp, crop_sz_tmp, xy=xy, verbose=debug, full_output = True)
            cy, cx = frame_center(tmp_tmp[0], verbose=debug)
            write_fits(self.outpath + '4_tmp_crop_'+ fits_name, tmp_tmp)
            tmp_tmp = cube_recenter_2dfit(tmp_tmp, xy=(int(cx),int(cy)), fwhm=self.resel_ori, subi_size=5, nproc=1, model='gauss',
                                                            full_output=False, verbose=debug, save_shifts=False, 
                                                            offset=None, negative=False, debug=False, threshold=False, plot = False)
            tmp_tmp = cube_crop_frames(tmp_tmp, crop_sz, xy=(cx,cy), verbose=verbose)
            write_fits(self.outpath+'4_centered_unsat_'+fits_name, tmp_tmp)
            for dd in range(self.new_ndit_unsat):
                psf_tmp[un*self.new_ndit_unsat+dd] = tmp_tmp[dd] #combining all frames in unsat to make master cube
        psf_med = np.median(psf_tmp, axis=0)
        write_fits(self.outpath+'master_unsat_psf.fits', psf_med)
        if verbose: 
            print('The median PSF of the star has been obtained')
        if plot == 'show':
            plot_frames(psf_med)
       
        data_frame  = fit_2dgaussian(psf_med, crop=False, cent=None, cropsize=15, fwhmx=self.resel_ori, fwhmy=self.resel_ori, 
                                                            theta=0, threshold=False, sigfactor=6, full_output=True, 
                                                            debug=False)
        data_frame = data_frame.astype('float64')
        self.fwhm_y = data_frame['fwhm_y'][0]
        self.fwhm_x = data_frame['fwhm_x'][0]
        self.fwhm_theta = data_frame['theta'][0]
        
        self.fwhm = (self.fwhm_y+self.fwhm_x)/2.0
        
        if verbose:
            print( "fwhm_y, fwhm x, theta and fwhm (mean of both):")
            print( self.fwhm_y, self.fwhm_x, self.fwhm_theta, self.fwhm)
        
        
        psf_med_norm, flux_unsat, fwhm_2 = normalize_psf(psf_med, fwhm=self.fwhm, full_output=True)
        write_fits(self.outpath+'master_unsat_psf_norm.fits', psf_med_norm)
        write_fits(self.outpath+'fwhm.fits',np.array([self.fwhm,self.fwhm_y,self.fwhm_x,self.fwhm_theta]))
        flux_psf = flux_unsat[0]*fits_info.dit_sci/fits_info.dit_unsat
        write_fits(self.outpath+'master_unsat-stellarpsf_fluxes.fits', np.array([flux_unsat[0],flux_psf]))
        if verbose:
            print( "Flux of the psf (in SCI frames): ", flux_psf)
            print( self.fwhm)   
            print( flux_unsat,flux_psf)
            
        
    def subtract_sky(self, imlib = 'opencv', npc = [1], mode = 'PCA', verbose = True, debug = False, plot = None, remove = False):
        """
        Sky subtraction of the science cubes 
        imlib : string: 'ndimage-interp', 'opencv'
        mode : string: 'PCA', 'median'
        npc : list, None
        plot options: 'save', 'show', None. Show or save relevant plots for debugging
        remove options: True, Flase. Cleans file for unused fits
        """
        
        #set up a check for necessary files
        
        sky_list = []
        with open(self.inpath +"sky_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                sky_list.append(line.split('\n')[0])
        n_sky = len(sky_list)
                
        sci_list = []
        with open(self.inpath +"sci_list.txt", "r") as f:
            tmp = f.readlines()
            for line in tmp:
                sci_list.append(line.split('\n')[0])
        n_sci = len(sci_list)
        
        if os.path.isfile(self.outpath + 'fwhm.fits') == False:
            raise NameError('FWHM of the star is not defined. Run: get_stellar_psf()')
        if os.path.isfile(self.outpath + '3_rmfr_' + sci_list[-1]) == False:
            raise NameError('Missing 3_rmfr_*.fits. Run: first_frame_removal()')
        
        self.final_sz = int(open_fits(self.outpath + 'final_sz')[0])
        self.com_sz = int(open_fits(self.outpath + 'common_sz')[0])
        self.new_ndit_sci = int(open_fits(self.outpath +'new_ndit_sci_sky_unsat')[0])
        self.new_ndit_sky = int(open_fits(self.outpath + 'new_ndit_sci_sky_unsat')[1])
        self.real_ndit_sky = int(open_fits(self.outpath + 'real_ndit_sky'))[1]
        #        with open(self.outpath+"real_ndit_sky_list.txt", "r") as f:
#            tmp = f.readlines()
#            for line in tmp:    
#                self.real_ndit_sky.append(int(line.split('\n')[0]))  
    
        sky_list_mjd = []
        #get times of unsat cubes (modified jullian calander)
        for fname in sky_list:
            tmp, header = open_fits(self.inpath +fname, header=True,
                                            verbose=debug)
            sky_list_mjd.append(header['MJD-OBS'])
            
        # SORT SKY_LIST in chronological order (important for calibration)
        arg_order = np.argsort(sky_list_mjd, axis=0)
        myorder = arg_order.tolist()
        sorted_sky_list = [sky_list[i] for i in myorder]
        sorted_sky_mjd_list = [sky_list_mjd[i] for i in myorder]
        sky_list = sorted_sky_list
        sky_mjd_list = np.array(sorted_sky_mjd_list)
        write_fits(self.outpath+"sky_mjd_times.fits",sky_mjd_list)
            
        tmp = open_fits(self.outpath+"TMP_med_bef_SKY_subtr.fits")
        self.fwhm = open_fits(self.outpath + 'fwhm.fits')[0]
        # try high pass filter to isolate blobs
        hpf_sz = int(2*self.fwhm)
        if not hpf_sz%2:
            hpf_sz+=1
        tmp = frame_filter_highpass(tmp, mode='median-subt', median_size=hpf_sz, 
                                              kernel_size=hpf_sz, fwhm_size=self.fwhm)
        if plot == 'show':
            plot_frames(tmp, title = 'Isolated dust grains')
        if plot == 'save':
            plot_frames(tmp, title = 'Isolated dust grains', save = self.outpath + 'Isolated_grains')        
        #then use the automatic detection tool of vip_hci.metrics
        snr_thr = 10
        snr_thr_all = 30
        psfn = open_fits(self.outpath+"master_unsat_psf_norm.fits")
        table_det = detection(tmp,psf=psfn, bkg_sigma=1, mode='lpeaks', matched_filter=True, 
                  mask=True, snr_thresh=snr_thr, plot=False, debug=False, 
                  full_output=True, verbose=debug)
        y_dust = table_det['y']
        x_dust = table_det['x']
        snr_dust = table_det['px_snr']
        
        
        # trim to just keep the specks with SNR>10 anywhere but in the lower left quadrant
        dust_xy_all=[]
        dust_xy_tmp=[]
        cy,cx = frame_center(tmp)
        for i in range(len(y_dust)):
            if not np.isnan(snr_dust[i]): # discard nan
                if abs(y_dust[i] - cy)>3*self.fwhm and abs(x_dust[i] - cx)>3*self.fwhm:
                    if snr_dust[i]>snr_thr_all:
                        dust_xy_all.append((x_dust[i],y_dust[i]))
                    if (y_dust[i] > cy or x_dust[i] >cx) and snr_dust[i]>snr_thr: # discard lower left quadrant
                        dust_xy_tmp.append((x_dust[i],y_dust[i]))
        ndust_all = len(dust_xy_all)
        
        ndust = len(dust_xy_tmp)
        if verbose:
            print(dust_xy_tmp)
            print("{} dust specks have been identified for alignment of SCI and SKY frames".format(ndust))
        
        # Fit them to gaussians in a test frame, and discard non-circular one (fwhm_y not within 20% of fwhm_x)

        test_xy = np.zeros([ndust,2])
        fwhm_xy = np.zeros([ndust,2])
        tmp = open_fits(self.outpath+"TMP_med_bef_SKY_subtr.fits")
        tmp = frame_filter_highpass(tmp, mode='median-subt', median_size=hpf_sz, 
                                            kernel_size=hpf_sz, fwhm_size=self.fwhm)
        bad_dust=[]
        self.resel_ori = fits_info.wavelength*206265/(fits_info.size_telescope*fits_info.pixel_scale)
        crop_sz = int(5*self.resel_ori)
        if crop_sz%2==0:
            crop_sz=crop_sz-1
    
            
        for dd in range(ndust):
            table_gaus = fit_2dgaussian(tmp, crop=True, cent=dust_xy_tmp[dd], 
                                        cropsize=crop_sz, fwhmx=self.resel_ori,                                                                             
                                        threshold=True, sigfactor=0,
                                        full_output=True, debug=False)
            test_xy[dd,1] = table_gaus['centroid_y'][0]
            test_xy[dd,0] = table_gaus['centroid_x'][0]
            fwhm_xy[dd,1] = table_gaus['fwhm_y'][0]
            fwhm_xy[dd,0] = table_gaus['fwhm_x'][0]
            amplitude = table_gaus['amplitude'][0]
            if fwhm_xy[dd,1]/fwhm_xy[dd,0] < 0.8 or fwhm_xy[dd,1]/fwhm_xy[dd,0]>1.2:
                bad_dust.append(dd)
            
        dust_xy = [xy for i, xy in enumerate(dust_xy_tmp) if i not in bad_dust]
        ndust = len(dust_xy)   
        if verbose:
            print("We detected {:.0f} non-circular dust specks, hence removed from the list.".format(len(bad_dust)))
            print("We are left with {:.0f} dust specks for alignment of SCI and SKY frames.".format(ndust))
        
        # the code first finds the exact coords of the dust features in the median of the first SCI cube (and show them)
        xy_cube0 = np.zeros([ndust, 2])
        crop_sz = int(3*self.resel_ori)
        tmp_cube = open_fits(self.outpath+'3_rmfr_'+sci_list[0], verbose=debug)
        tmp_med = np.median(tmp_cube, axis=0)
        tmp = frame_filter_highpass(tmp_med, mode='median-subt', median_size=hpf_sz, 
                                        kernel_size=hpf_sz, fwhm_size=self.fwhm)
        for dd in range(ndust):
            try:
                df = fit_2dgaussian(tmp, crop=True, cent=dust_xy[dd], cropsize=crop_sz, fwhmx=self.resel_ori, fwhmy=self.resel_ori, 
                                                                                                      theta=0, threshold=True, sigfactor=0, full_output=True, 
                                                                                                      debug=False)
                xy_cube0[dd,1] = df['centroid_y'][0]
                xy_cube0[dd,0] = df['centroid_x'][0]
                fwhm_y = df['fwhm_y'][0]
                fwhm_x = df['fwhm_x'][0]
                amplitude = df['amplitude'][0]
                if verbose:
                    print( "coord_x: {}, coord_y: {}, fwhm_x: {}, fwhm_y:{}, amplitude: {}".format(xy_cube0[dd,0], xy_cube0[dd,1], fwhm_x, fwhm_y, amplitude)) 
                shift_xy_dd = (xy_cube0[dd,0]-dust_xy[dd][0], xy_cube0[dd,1]-dust_xy[dd][1])
                if verbose:
                    print( "shift with respect to center for dust grain #{}: {}".format(dd,shift_xy_dd))
            except ValueError:
                xy_cube0[dd,0], xy_cube0[dd,1] = dust_xy[dd]
                print( "!!! Gaussian fit failed for dd = {}. We set position to first (eye-)guess position.".format(dd))
        print( "Note: the shifts should be small if the eye coords of each dust grain were well provided!")
        
        
        # then it finds the centroids in all other frames (SCI+SKY) to determine the relative shifts to be applied to align all frames
        shifts_xy_sci = np.zeros([ndust, n_sci, self.new_ndit_sci, 2])
        shifts_xy_sky = np.zeros([ndust, n_sky, self.new_ndit_sky, 2])
        crop_sz = int(3*self.resel_ori)
        
        t0 = time_ini()
    
        # SCI frames
        bar = pyprind.ProgBar(n_sci, stream=1, title='Finding shifts to be applied to the SCI frames')
        for sc, fits_name in enumerate(sci_list):
            tmp_cube = open_fits(self.outpath+'3_rmfr_'+fits_name, verbose=debug)
            for zz in range(tmp_cube.shape[0]):
                tmp = frame_filter_highpass(tmp_cube[zz], mode='median-subt', median_size=hpf_sz, 
                                        kernel_size=hpf_sz, fwhm_size=self.fwhm)
                for dd in range(ndust):
                    try: # note we have to do try, because for some (rare) channels the gaussian fit fails
                        y_tmp,x_tmp = fit_2dgaussian(tmp, crop=True, cent=dust_xy[dd], cropsize=crop_sz, 
                                                             fwhmx=self.resel_ori, fwhmy=self.resel_ori, full_output= False, debug = False)
                    except ValueError:
                        x_tmp,y_tmp = dust_xy[dd]
                        if verbose:
                            print( "!!! Gaussian fit failed for sc #{}, dd #{}. We set position to first (eye-)guess position.".format(sc, dd))
                    shifts_xy_sci[dd,sc,zz,0] = xy_cube0[dd,0] - x_tmp 
                    shifts_xy_sci[dd,sc,zz,1] = xy_cube0[dd,1] - y_tmp
            bar.update()
    
        # SKY frames
        bar = pyprind.ProgBar(n_sky, stream=1, title='Finding shifts to be applied to the SKY frames')
        for sk, fits_name in enumerate(sky_list):
            tmp_cube = open_fits(self.outpath+'3_rmfr_'+fits_name, verbose=debug)
            for zz in range(tmp_cube.shape[0]):
                tmp = frame_filter_highpass(tmp_cube[zz], mode='median-subt', median_size=hpf_sz, 
                                        kernel_size=hpf_sz, fwhm_size=self.fwhm)
                #check tmp after highpass filter 
                for dd in range(ndust):
                    try:
                        y_tmp,x_tmp = fit_2dgaussian(tmp, crop=True, cent=dust_xy[dd], cropsize=crop_sz, 
                                                             fwhmx=self.resel_ori, fwhmy=self.resel_ori, full_output = False, debug = False)
                    except ValueError:
                        x_tmp,y_tmp = dust_xy[dd]
                        if verbose:
                            print( "!!! Gaussian fit failed for sk #{}, dd #{}. We set position to first (eye-)guess position.".format(sc, dd))
                    shifts_xy_sky[dd,sk,zz,0] = xy_cube0[dd,0] - x_tmp 
                    shifts_xy_sky[dd,sk,zz,1] = xy_cube0[dd,1] - y_tmp
            bar.update()
        time_fin(t0)
        
        
        #try to debug the fit, check dust pos
        if verbose:
            print( "Max stddev of the shifts found for the {} dust grains: ".format(ndust), np.amax(np.std(shifts_xy_sci, axis=0)))
            print( "Min stddev of the shifts found for the {} dust grains: ".format(ndust), np.amin(np.std(shifts_xy_sci, axis=0)))
            print( "Median stddev of the shifts found for the {} dust grains: ".format(ndust), np.median(np.std(shifts_xy_sci, axis=0)))
            print( "Median shifts found for the {} dust grains (SCI): ".format(ndust), np.median(np.median(np.median(shifts_xy_sci, axis=0),axis=0),axis=0))
            print( "Median shifts found for the {} dust grains: (SKY)".format(ndust), np.median(np.median(np.median(shifts_xy_sky, axis=0),axis=0),axis=0))
        
        shifts_xy_sci_med = np.median(shifts_xy_sci, axis=0)
        shifts_xy_sky_med = np.median(shifts_xy_sky, axis=0)
        
        
        for sc, fits_name in enumerate(sci_list):
            try:
                tmp = open_fits(self.outpath+'3_rmfr_'+fits_name, verbose=debug)
                tmp_tmp_tmp_tmp = np.zeros_like(tmp)
                for zz in range(tmp.shape[0]):
                    tmp_tmp_tmp_tmp[zz] = frame_shift(tmp[zz], shifts_xy_sci_med[sc,zz,1], shifts_xy_sci_med[sc,zz,0], imlib=imlib)
                write_fits(self.outpath+'3_AGPM_aligned_imlib_'+fits_name, tmp_tmp_tmp_tmp)
                if remove:
                    os.system("rm "+self.outpath+'3_rmfr_'+fits_name)
            except:
                print("file #{} not found".format(sc))
    
        for sk, fits_name in enumerate(sky_list):
            tmp = open_fits(self.outpath + '3_rmfr_'+fits_name, verbose=debug)
            tmp_tmp_tmp_tmp = np.zeros_like(tmp)
            for zz in range(tmp.shape[0]): 
                tmp_tmp_tmp_tmp[zz] = frame_shift(tmp[zz], shifts_xy_sky_med[sk,zz,1], shifts_xy_sky_med[sk,zz,0], imlib=imlib)
            write_fits(self.outpath+'3_AGPM_aligned_imlib_'+fits_name, tmp_tmp_tmp_tmp)        
            if remove:
                os.system("rm "+self.outpath+'3_rmfr_'+fits_name)

 
        ################## MEDIAN ##################################         
        if mode == 'median':      
            sci_list_test = [sci_list[0],sci_list[int(n_sci/2)],sci_list[-1]] # first test then do with all sci_list
             
            master_skies2 = np.zeros([n_sky,self.final_sz,self.final_sz])
            master_sky_times = np.zeros(n_sky)
        
            for sk, fits_name in enumerate(sky_list):
                tmp_tmp_tmp = open_fits(self.outpath+'3_AGPM_aligned_imlib_'+fits_name, verbose=debug)
                _, head_tmp = open_fits(self.inpath+fits_name, header=True, verbose=debug)
                master_skies2[sk] = np.median(tmp_tmp_tmp,axis=0)
                master_sky_times[sk]=head_tmp['MJD-OBS']
            write_fits(self.outpath+"master_skies_imlib.fits", master_skies2)
            write_fits(self.outpath+"master_sky_times.fits", master_sky_times)
            
            master_skies2 = open_fits(self.outpath +"master_skies_imlib.fits", verbose=debug)
            master_sky_times = open_fits(self.outpath +"master_sky_times.fits",verbose=debug)
            
            bar = pyprind.ProgBar(n_sci, stream=1, title='Subtracting sky with closest frame in time')
            for sc, fits_name in enumerate(sci_list_test):
                tmp_tmp_tmp_tmp = open_fits(self.outpath+'3_AGPM_aligned_imlib_'+fits_name, verbose=debug) 
                tmpSKY2 = np.zeros_like(tmp_tmp_tmp_tmp) ###
                _, head_tmp = open_fits(self.inpath+fits_name, header=True, verbose=debug)
                sc_time = head_tmp['MJD-OBS']
                idx_sky = find_nearest(master_sky_times,sc_time)
                tmpSKY2 = tmp_tmp_tmp_tmp-master_skies2[idx_sky] 
                write_fits(self.outpath+'4_sky_subtr_imlib_'+fits_name, tmpSKY2, verbose=debug) ###
            bar.update()
            if plot:
                old_tmp = np.median(open_fits(self.outpath+'3_AGPM_aligned_imlib_'+sci_list[0]), axis=0)
                old_tmp_tmp = np.median(open_fits(self.outpath+'3_AGPM_aligned_imlib_'+sci_list[-1]), axis=0)
                tmp = np.median(open_fits(self.outpath+'4_sky_subtr_imlib_'+sci_list[0]), axis=0)
                tmp_tmp = np.median(open_fits(self.outpath+'4_sky_subtr_imlib_'+sci_list[-1]), axis=0)
            if plot == 'show':
                plot_frames((old_tmp,old_tmp_tmp,tmp,tmp_tmp))
            if plot == 'save': 
                plot_frames((old_tmp,old_tmp_tmp,tmp,tmp_tmp), save = self.outpath + 'SCI_median_sky_subtraction')
                
         ############## PCA ##############
         
        if mode == 'PCA':            
            master_skies2 = np.zeros([n_sky,self.final_sz,self.final_sz])
            master_sky_times = np.zeros(n_sky)
            for sk, fits_name in enumerate(sky_list):
                tmp_tmp_tmp = open_fits(self.outpath+'3_AGPM_aligned_imlib_'+fits_name, verbose=debug)
                _, head_tmp = open_fits(self.inpath+fits_name, header=True, verbose=debug)
                master_skies2[sk] = np.median(tmp_tmp_tmp,axis=0)
                master_sky_times[sk]=head_tmp['MJD-OBS']
            write_fits(self.outpath+"master_skies_imlib.fits", master_skies2)
            write_fits(self.outpath+"master_sky_times.fits", master_sky_times)
            
            
            all_skies_imlib = np.zeros([n_sky*self.new_ndit_sky,self.final_sz,self.final_sz])
            for sk, fits_name in enumerate(sky_list):
                tmp = open_fits(self.outpath+'3_AGPM_aligned_imlib_'+fits_name, verbose=debug)
                all_skies_imlib[sk*self.new_ndit_sky:(sk+1)*self.new_ndit_sky] = tmp[:self.new_ndit_sky]
    
            # Define mask for the region where the PCs will be optimal
            #make sure the mask avoids dark region. 
            mask_arr = np.ones([self.com_sz,self.com_sz])
            mask_inner_rad = int(3/fits_info.pixel_scale)
            mask_width = int(self.shadow_r*0.8-mask_inner_rad)
            mask_AGPM = get_annulus_segments(mask_arr, mask_inner_rad, mask_width, mode = 'mask')[0]
            mask_AGPM = frame_crop(mask_AGPM,self.final_sz)
            # Do PCA subtraction of the sky
            tmp = np.median(tmp,axis = 0)
            if plot == 'show':
                plot_frames((tmp,mask_AGPM),vmin = (0,0), vmax = (20000,1))
            if plot == 'save':
                plot_frames((tmp,mask_AGPM),vmin = (0,0), vmax = (20000,1), save = self.outpath + 'PCA_sky_subtract_mask')
                
            if verbose: 
                print('Begining PCA subtraction')
            if npc is None:
                #nnpc_tmp = np.array([1,2,3,4,5,10,20,40,60])
                nnpc_tmp = np.array([1,2])
                nnpc = np.array([pc for pc in nnpc_tmp if pc < n_sky*self.new_ndit_sky])
                npc_opt = np.zeros(len(sci_list))
                bar = pyprind.ProgBar(n_sci, stream=1, title='Subtracting sky with PCA')
                for sc, fits_name in enumerate(sci_list):
                    _, head = open_fits(self.inpath+fits_name, verbose=debug, header=True)
                    sc_time = head['MJD-OBS']
                    idx_sky = find_nearest(master_sky_times,sc_time)
                    tmp = open_fits(self.outpath+'3_AGPM_aligned_imlib_'+fits_name, verbose=debug)
                    pca_lib = all_skies_imlib[int(np.sum(self.real_ndit_sky[:idx_sky])):int(np.sum(self.real_ndit_sky[:idx_sky+1]))]
                    med_sky = np.median(pca_lib,axis=0)
                    mean_std = np.zeros(nnpc.shape[0])
                    hmean_std = np.zeros(nnpc.shape[0])
                    for nn, npc_tmp in enumerate(nnpc):
                        tmp_tmp = cube_subtract_sky_pca(tmp-med_sky, all_skies_imlib-med_sky, 
                                                                    mask_AGPM, ref_cube=None, ncomp=npc_tmp)
                        write_fits(self.outpath+'4_sky_subtr_medclose1_npc{}_imlib_'.format(npc_tmp)+fits_name, tmp_tmp, verbose=debug)
                        # measure mean(std) in all apertures in tmp_tmp, and record for each npc
                        std = np.zeros(ndust_all)
                        for dd in range(ndust_all):
                            std[dd] = np.std(get_circle(np.median(tmp_tmp,axis=0), 3*self.fwhm, mode = 'val', 
                                                                cy=dust_xy_all[dd][1], cx=dust_xy_all[dd][0]))
                        mean_std[nn] = np.mean(std)
                        std_sort = np.sort(std)
                        hmean_std[nn] = np.mean(std_sort[int(ndust_all/2.):])
                    npc_opt[sc] = nnpc[np.argmin(hmean_std)]
                    if verbose:
                        print("***** SCI #{:.0f} - OPTIMAL NPC = {:.0f} *****\n".format(sc,npc_opt[sc]))
                    nnpc_bad = [pc for pc in nnpc if pc!=npc_opt[sc]]
                    if remove:
                        os.system("rm "+self.outpath+'3_AGPM_aligned_imlib_'+fits_name)
                        for npc_bad in nnpc_bad:
                            os.system("rm "+self.outpath+'4_sky_subtr_medclose1_npc{:.0f}_imlib_'.format(npc_bad)+fits_name)
                            os.system("mv "+self.outpath+'4_sky_subtr_medclose1_npc{:.0f}_imlib_'.format(npc_opt[sc])+fits_name + ' ' + self.outpath+'4_sky_subtr_imlib_'+fits_name)
                    else: 
                        os.system("cp "+self.outpath+'4_sky_subtr_medclose1_npc{:.0f}_imlib_'.format(npc_opt[sc])+fits_name + ' ' + self.outpath+'4_sky_subtr_imlib_'+fits_name)

                    bar.update()
                write_fits(self.outpath+"TMP_npc_opt.fits",npc_opt)
            if type(npc) is list:
                nnpc = np.array([pc for pc in npc if pc < n_sky*self.new_ndit_sky])
                npc_opt = np.zeros(len(sci_list))
                bar = pyprind.ProgBar(n_sci, stream=1, title='Subtracting sky with PCA')
                for sc, fits_name in enumerate(sci_list):
                    _, head = open_fits(self.inpath+fits_name, verbose=debug, header=True)
                    sc_time = head['MJD-OBS']
                    idx_sky = find_nearest(master_sky_times,sc_time)
                    tmp = open_fits(self.outpath+'3_AGPM_aligned_imlib_'+fits_name, verbose=debug)
                    pca_lib = all_skies_imlib[int(np.sum(self.real_ndit_sky[:idx_sky])):int(np.sum(self.real_ndit_sky[:idx_sky+1]))]
                    med_sky = np.median(pca_lib,axis=0)
                    mean_std = np.zeros(nnpc.shape[0])
                    hmean_std = np.zeros(nnpc.shape[0])
                    for nn, npc_tmp in enumerate(nnpc):
                        tmp_tmp = cube_subtract_sky_pca(tmp-med_sky, all_skies_imlib-med_sky, 
                                                                    mask_AGPM, ref_cube=None, ncomp=npc_tmp)
                        write_fits(self.outpath+'4_sky_subtr_medclose1_npc{}_imlib_'.format(npc_tmp)+fits_name, tmp_tmp, verbose=debug)
                        # measure mean(std) in all apertures in tmp_tmp, and record for each npc
                        std = np.zeros(ndust_all)
                        for dd in range(ndust_all):
                            std[dd] = np.std(get_circle(np.median(tmp_tmp,axis=0), 3*self.fwhm, mode = 'val', 
                                                                cy=dust_xy_all[dd][1], cx=dust_xy_all[dd][0]))
                        mean_std[nn] = np.mean(std)
                        std_sort = np.sort(std)
                        hmean_std[nn] = np.mean(std_sort[int(ndust_all/2.):])
                    npc_opt[sc] = nnpc[np.argmin(hmean_std)]
                    if verbose:
                        print("***** SCI #{:.0f} - OPTIMAL NPC = {:.0f} *****\n".format(sc,npc_opt[sc]))
                    nnpc_bad = [pc for pc in nnpc if pc!=npc_opt[sc]]
                    if remove:
                        os.system("rm "+self.outpath+'3_AGPM_aligned_imlib_'+fits_name)
                        os.system("mv "+self.outpath+'4_sky_subtr_medclose1_npc{:.0f}_imlib_'.format(npc_opt[sc])+fits_name + ' ' + self.outpath+'4_sky_subtr_imlib_'+fits_name)
                        for npc_bad in nnpc_bad:
                            os.system("rm "+self.outpath+'4_sky_subtr_medclose1_npc{:.0f}_imlib_'.format(npc_bad)+fits_name)
                    else: 
                        os.system("cp "+self.outpath+'4_sky_subtr_medclose1_npc{:.0f}_imlib_'.format(npc_opt[sc])+fits_name + ' ' + self.outpath+'4_sky_subtr_imlib_'+fits_name)
                    bar.update()
                write_fits(self.outpath+"TMP_npc_opt.fits",npc_opt)
                
            else:
                bar = pyprind.ProgBar(n_sci, stream=1, title='Subtracting sky with PCA')
                for sc, fits_name in enumerate(sci_list_test):
                    tmp = open_fits(self.outpath+'3_AGPM_aligned_imlib_'+fits_name, verbose=debug)
                    tmp_tmp = cube_subtract_sky_pca(tmp, all_skies_imlib, mask_AGPM, ref_cube=None, ncomp=npc)
                    write_fits(self.outpath+'4_sky_subtr_imlib_'+fits_name, tmp_tmp, verbose=debug)
                    bar.update()
                    if remove:
                        os.system("rm "+self.outpath+'3_AGPM_aligned_imlib_'+fits_name)
                        
            if verbose:
                print('Finished PCA dark subtraction')
            if plot:
                if npc is None:
                    # ... IF PCA WITH DIFFERENT NPCs 
                    old_tmp = np.median(open_fits(self.outpath+'3_AGPM_aligned_imlib_'+sci_list[-1]), axis=0)   
                    tmp = np.median(open_fits(self.outpath+'4_sky_subtr_npc{}_imlib_'.format(1)+sci_list[-1]), axis=0)
                    tmp_tmp = np.median(open_fits(self.outpath+'4_sky_subtr_npc{}_imlib_'.format(5)+sci_list[-1]), axis=0)
                    tmp_tmp_tmp = np.median(open_fits(self.outpath+'4_sky_subtr_npc{}_imlib_'.format(100)+sci_list[-1]), axis=0)
                    tmp2 = np.median(open_fits(self.outpath+'4_sky_subtr_npc{}_no_shift_'.format(1)+sci_list[-1]), axis=0)
                    tmp_tmp2 = np.median(open_fits(self.outpath+'4_sky_subtr_npc{}_no_shift_'.format(5)+sci_list[-1]), axis=0)
                    tmp_tmp_tmp2 = np.median(open_fits(self.outpath+'4_sky_subtr_npc{}_no_shift_'.format(100)+sci_list[-1]), axis=0)
                    if plot == 'show': 
                        plot_frames((tmp, tmp_tmp, tmp_tmp_tmp, tmp2, tmp_tmp2, tmp_tmp_tmp2))
                    if plot == 'save': 
                        plot_frames((tmp, tmp_tmp, tmp_tmp_tmp, tmp2, tmp_tmp2, tmp_tmp_tmp2), save = self.outpath + 'SCI_PCA_dark_subtraction')   
                else:
                    # ... IF PCA WITH A SPECIFIC NPC
                    old_tmp = np.median(open_fits(self.outpath+'3_AGPM_aligned_imlib_'+sci_list[0]), axis=0) 
                    old_tmp_tmp = np.median(open_fits(self.outpath+'3_AGPM_aligned_imlib_'+sci_list[int(n_sci/2)]), axis=0) 
                    old_tmp_tmp_tmp = np.median(open_fits(self.outpath+'3_AGPM_aligned_'+sci_list[-1]), axis=0) 
                    tmp2 = np.median(open_fits(self.outpath+'4_sky_subtr_imlib_'+sci_list[0]), axis=0)
                    tmp_tmp2 = np.median(open_fits(self.outpath+'4_sky_subtr_imlib_'+sci_list[int(n_sci/2)]), axis=0)
                    tmp_tmp_tmp2 = np.median(open_fits(self.outpath+'4_sky_subtr_imlib_'+sci_list[-1]), axis=0)  
                    if plot == 'show':
                        plot_frames((old_tmp, old_tmp_tmp, old_tmp_tmp_tmp, tmp2, tmp_tmp2, tmp_tmp_tmp2))
                    if plot == 'save': 
                        plot_frames((tmp, tmp_tmp, tmp_tmp_tmp, tmp2, tmp_tmp2, tmp_tmp_tmp2), save = self.outpath + 'SCI_PCA_dark_subtraction')
                        
                        
    def clean_fits(self, debug = False, verbose = True):
        """
        Use this method to clean for any intermediate fits files
        """
        #be careful when using avoid removing PSF related fits
        os.system("rm "+self.outpath+'common_sz.fits')
        os.system("rm "+self.outpath+'real_ndit_sci_sky.fits')
        os.system("rm "+self.outpath+'new_ndit_sci_sky_unsat.fits')
        os.system("rm "+self.outpath+'fwhm.fits')
        os.system("rm "+self.outpath+'final_sz.fits')
        os.system("rm "+self.outpath+'flat_dark_cube.fits')
        os.system("rm "+self.outpath+'master_bpix_map.fits')
        os.system("rm "+self.outpath+'master_bpix_map_2ndcrop.fits')
        os.system("rm "+self.outpath+'master_bpix_map_unsat.fits')
        os.system("rm "+self.outpath+'master_flat_field.fits')
        os.system("rm "+self.outpath+'master_flat_field_unsat.fits')
        os.system("rm "+self.outpath+'master_skies_imlib.fits')
        os.system("rm "+self.outpath+'master_sky_times.fits')
        os.system("rm "+self.outpath+'master_unsat_psf.fits')
        os.system("rm "+self.outpath+'master_unsat_psf_norm.fits')
        os.system("rm "+self.outpath+'master_unsat-stellarpsf_fluxes.fits')
        os.system("rm "+self.outpath+'shadow_median_frame.fits')
        os.system("rm "+self.outpath+'sci_dark_cube.fits')
        os.system("rm "+self.outpath+'sky_mjd_times.fits')
        os.system("rm "+self.outpath+'TMP_2_master_median_SCI.fits')
        os.system("rm "+self.outpath+'TMP_2_master_median_SKY.fits')
        os.system("rm "+self.outpath+'TMP_med_bef_SKY_subtr.fits')
        os.system("rm "+self.outpath+'TMP_npc_opt.fits')
        os.system("rm "+self.outpath+'unsat_dark_cube.fits')
        

            
            
            
