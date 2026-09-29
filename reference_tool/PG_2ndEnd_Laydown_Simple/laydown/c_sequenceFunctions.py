#from glob import glob
import json
import math
import OrcFxAPI as of

from . import b_builderFunctions
from . import d_extractFunctions

from scipy import optimize
import numpy as np
import pandas as pd

'''
Script      :   c_sequenceFunctions.py

Function    :   Contains functions that serve the following purposes:
                * minimise the wire lift by moving vesselX
                * minimise the pipe lift by moving vesselX (for the pallet step)
                * release PLET rotation DOFs
                * calculate the required payout to reach certain compulsory steps
                * change ramp angle to jack down
                * produce the buoy-deployment sequence steps
                * produce the rest of the static sequence until landing
                
Dependents  :   * UI_func.py
                
Last update :   22 April 2026
Author      :   S.O
'''
def solve_pipeLift_pallet(
    model               : of.Model,
    payout              : float,
    firstGuessVesselX   : float,
    line_dict           : dict,
    solvingFile         : str,
    prev_vesselX        : float,
    #conv_flag           : int,
    mylog               : object
):
    '''
    Function    : Moves the vessel X to optimise for minimum pipe lift (measured as the declination of the Bottom Pipe a length of 12.2m from the anchor flange at the structure).
    
    Returns     : optimised model, convergence flag
    
    '''
    vessel_name = line_dict["vesselGeneral"].get("VesselSelected")
    vessel      = model[vessel_name.split(" ")[-1]]
    structure   = model["PLET_Frame"]
    ramp        = model[line_dict["vesselGeneral"].get("VesselRamp")]
    wire        = model["Wire1"]   # CHANGE THIS
    pipe_bot    = model["Pipe1"]
    wd          = float(line_dict["General"].get("WD"))
       
    ramp_angle_c        = np.radians(90 - abs(ramp.InitialRotation2))
    ramp_angle          = abs(ramp.InitialRotation2)
        
    # Initial Bounds
    if wd < 1000:
        lowerBoundX = prev_vesselX - 0.25*wd       
        upperBoundX = prev_vesselX + 0.25*wd
    else:
        lowerBoundX = prev_vesselX - 0.125*wd       
        upperBoundX = prev_vesselX + 0.125*wd
        
    # Set the structure initial position
    structure.InitialZ  = 15.0
    structure_depth     = abs(structure.InitialZ)
    structure_clearance = wd - structure_depth
       
    # moved ilt beam mover to the loop
    
    def _eqnVesselAdjust_pipeAngle(vesselX, tol):
        
        vessel.InitialX = vesselX
        
        if vessel.Name == "Vega":
            structure.InitialX = vessel.InitialX - 20
        elif vessel.Name == "Oceans":
            structure.InitialX = vessel.InitialX - 100
        elif vessel.Name == "Navica":
            structure.InitialX = vessel.InitialX - 60
            
        try:
            beam = model["A&R spreader beam"]
            if vessel.Name == "Vega":
                beam.InitialX = vessel.InitialX - 20
            elif vessel.Name == "Oceans":
                beam.InitialX = vessel.InitialX - 100
            elif vessel.Name == "Navica":
                beam.InitialX = vessel.InitialX - 60
        except:
            pass
        
        ##########
        # Move the AR beam if using 
        #useILT = line_dict["sequenceGeneral"].get("UseILTBeam")
        #if useILT:
        #    ILTbeam          = model["A&R spreader beam"]
        #    pipeTopLen       = pipe_top.CumulativeLength[0]
        #    #
        #    pipeTopFlangeX   = pipe_top.EndBX   #wrt structure
        #    pipeTopFlangeZ   = pipe_top.EndBZ   #wrt structure        
        #    struct_xdisp     = pipeTopFlangeX*math.cos(math.radians(ramp_angle))
        #    struct_ydisp     = pipeTopFlangeZ*math.sin(math.radians(ramp_angle))
        #    #
        #    beam_xdisp       = pipeTopLen*math.cos(math.radians(ramp_angle))
        #    beam_ydisp       = 2.0*pipeTopLen*math.sin(math.radians(ramp_angle))
        #    ILTbeam.InitialX = structure.InitialX + struct_xdisp + beam_xdisp
        #    ILTbeam.InitialZ = structure.InitialZ + struct_ydisp + beam_ydisp
        #    ILTbeam.DegreesOfFreedomInStatics = "X,Y,Z"
        #
        #    print("MOVED THE AR BEAM: %.2f, %.2f" % (ILTbeam.InitialX, ILTbeam.InitialZ))
        #    print("STRUCTURE: %.2f, %.2f" % (structure.InitialX, structure.InitialZ))
        #    print("#################################################")
        
                   
        mylog.write("Optimizing with scipy vesselX: %.3f , structure x: %.1f, plet z: %.3f, payout: %.1f \n" % (vessel.InitialX, structure.InitialX, structure.InitialZ, payout))
        mylog.flush()
        
        try: 
            model.CalculateStatics()
            pipeDeclin  = (pipe_bot.StaticResult("Declination", objectExtra = of.oeArcLength(12.2)) - 90)
            deltaAngle  = pipeDeclin - ramp_angle
            print(f"Declination: {pipeDeclin}")
            mylog.write("Pipe Declination: %.2f, delta: %.2f \n" % (pipeDeclin, deltaAngle))
            mylog.flush()
        except:
            mylog.write("Cannot converge with vesselx: %.1f \n" % vessel.InitialX)
            mylog.flush()

        if abs(deltaAngle) <= tol:  
            return 0.0
        
        mylog.write("SUCCESSLY DID THE SCALAR SOLVE \n")

        return deltaAngle
    
    # Call the solver
    try:        
        xbounds = [lowerBoundX, upperBoundX]
        mylog.write(f"Trying scalar rootfinder with BOUNDS: [{lowerBoundX}, {upperBoundX}] and Tol: 0.5 \n")
        mylog.flush()
        
        optim = optimize.root_scalar(_eqnVesselAdjust_pipeAngle, bracket = xbounds, method = 'brentq', args = (0.5) )
                
        print(f"optim: {optim}")
        mylog.write(f"Optimization result: {optim}\n")
        mylog.flush()
        
        vessel.InitialX = optim.root       
        #conv_flag       = 1
        
    except:
        failed_filename = '%s-Failed.dat' % (solvingFile)
        mylog.write("ROOTFINDER has failed to find a solution. Saving failed run as %s.\n" % failed_filename)
        mylog.flush()
        model.SaveData(failed_filename)  
        #conv_flag = 0
            
    return model   #, conv_flag
  
def solve_PipeLiftPallet_old(
    initVesselX : float, 
    model       : object, 
    vessel      : object, 
    rampAngle   : float, 
    pipe        : object, 
    plet        : object, 
    vessel_json : json, 
    mylog       : any
    ):
    """
    Function    : Solves for vessel X position to return minimal pipe lift for the step where the PLET is resting on the pallet.
    Returns     : Optimised pipe clearance  
    
    """         
    vessel.InitialX = initVesselX    
    plet.InitialZ   = vessel_json["Pallet Height from Sea Level"]
    plet.InitialX   = initVesselX - vessel_json["Centroid-Stern Distance"] - 10
               
    mylog.write("Optimizing pipe lift for pallet step with vessel X: %.3f \n" % vessel.InitialX)
    mylog.flush()

    try: 
        model.CalculateStatics()
        pipe_Ax = pipe.StaticResult("X", objectExtra = of.oeEndA) 
        pipe_Az = pipe.StaticResult("Z", objectExtra = of.oeEndA)
        pipe_Nx = pipe.StaticResult("X", objectExtra = of.oeArcLength(10.0)) 
        pipe_Nz = pipe.StaticResult("Z", objectExtra = of.oeArcLength(10.0))
        
        aveAngle = math.degrees(1.5708 - math.atan((pipe_Ax-pipe_Nx)/(pipe_Az-pipe_Nz))) # 90deg(1.57rad)
        
        clearance = abs(rampAngle) - abs(aveAngle) 
        
        mylog.write("Clearance: %.2f degrees\n" % clearance)
        mylog.flush()
    except:
        mylog.write("Cannot converge with vesselX: %.1f\n" % vessel.InitialX)
        
    if abs(clearance) <= 0.25:
        return 0.0
    
    return clearance
        
def solve_WireLift(
    model               : object, 
    payout              : float, 
    firstGuessVesselX   : float, 
    line_dict           : dict, 
    solving_file        : str, 
    prev_vesselX        : float, 
    conv_flag           : int, 
    is_jackingdown      : bool, 
    mylog               : any, 
    first_step=None
    ):
    '''
    Function    : Moves vessel X to optimise for minimum wire lift
                    solving_file = "%s/%s_Stage_%s" %  % (jobpath, saveas, identifier)    
    Returns     : optimised model, convergence flag
    '''   
    vessel_name = line_dict["vesselGeneral"].get("VesselSelected")
    vessel      = model[vessel_name.split(" ")[-1]]
    wire        = model["Wire1"]
    plet        = model["PLET_Frame"]
    ramp        = model[line_dict["vesselGeneral"].get("VesselRamp")]
    wd          = float(line_dict["General"].get("WD"))
    init_plet_x = plet.InitialX
    ramp_angle_c   = np.radians(90 - abs(ramp.InitialRotation2))
    plet_depth     = abs(plet.InitialZ)
    plet_clearance = wd - plet_depth
        
    if first_step == True:
        if wd > 800:
            lowerBoundX = prev_vesselX - 0.125*wd
            upperBoundX = prev_vesselX + 0.125*wd
        else:
            lowerBoundX = prev_vesselX - 0.33*wd
            upperBoundX = prev_vesselX + 0.50*wd
        
    else:      
        if conv_flag == 0:
            if plet_clearance > 100:
                lowerBoundX    = init_plet_x + 0.1*(plet_depth*np.tan(ramp_angle_c))
            elif plet_clearance < 100 and plet_clearance > 10:
                lowerBoundX    = init_plet_x + 0.3*(plet_depth/np.tan(ramp_angle_c))
            else:
                lowerBoundX    = init_plet_x + 0.75*(plet_depth/np.tan(ramp_angle_c))

        elif conv_flag == 1:
            #lowerBoundX = max(lowerBoundX, prev_vesselX)  #suggest change this to prev vesselx ONLY
            #lowerBoundX = max(init_plet_x, prev_vesselX)  #does not work for big payouts
            lowerBoundX = prev_vesselX + 0.75*payout

        if is_jackingdown:
            lowerBoundX = max(init_plet_x, prev_vesselX)
            if plet_clearance < 50:
                if wd <= 1000:
                    upperBoundX = max(init_plet_x, prev_vesselX) + 0.5*wd
                else:
                    upperBoundX = max(init_plet_x, prev_vesselX) + 0.25*wd
            else:
                if wd > 800:
                    upperBoundX = max(init_plet_x, prev_vesselX) + 0.1*wd 
                else:
                    upperBoundX = max(init_plet_x, prev_vesselX) + 0.3*wd        
        else:
            upperBoundX = max(init_plet_x, prev_vesselX) + 1.75*payout
            
    attempted_vals = []
    
    def _eqnVesselAdjust_abs(vesselX):
        
        vessel.InitialX = vesselX
        
        if first_step:
            if vessel.Name == "Vega":
                plet.InitialX = vessel.InitialX - 50
            elif vessel.Name == "Oceans":
                plet.InitialX = vessel.InitialX - 100
            elif vessel.Name == "Navica":
                plet.InitialX = vessel.InitialX - 60
    
        mylog.write("Optimizing with scipy vesselX: %.3f , plet x: %.1f, plet z: %.3f \n" % (vessel.InitialX, plet.InitialX, plet.InitialZ))
        mylog.flush()

        try: 
            model.CalculateStatics()
            wireAngle = wire.StaticResult("Node declination", objectExtra = of.oeEndA) - 90
            clearance = abs(-1*ramp.InitialRotation2 - wireAngle)
            mylog.write("clearance: %.2f\n" % clearance)
            mylog.flush()
        except:
            mylog.write("Cannot converge with vesselx: %.1f and wire length %.1f\n" % (vessel.InitialX, wire.CumulativeLength[-1]))

        if clearance <= 1.0:
            return 0.0

        return clearance
    
    def _eqnVesselAdjust_signed(vesselX):
        
        vessel.InitialX = vesselX
        attempted_vals.append(vesselX)
        mylog.write("Optimizing with scipy vesselX: %.3f , plet x: %.1f, plet z: %.3f \n" % (vessel.InitialX, plet.InitialX, plet.InitialZ))
        mylog.flush()
        
        if first_step:
            if vessel.Name == "Vega":
                plet.InitialX = vessel.InitialX - 50
            elif vessel.Name == "Oceans":
                plet.InitialX = vessel.InitialX - 100
            elif vessel.Name == "Navica":
                plet.InitialX = vessel.InitialX - 60
        
        try: 
            model.CalculateStatics()
            wireAngle = wire.StaticResult("Node declination", objectExtra = of.oeEndA) - 90
            clearance = -1*ramp.InitialRotation2 - wireAngle
            mylog.write("clearance: %.2f\n" % clearance)
            mylog.flush()
        except:
            mylog.write("Cannot converge with vesselx: %.1f and wire length %.1f\n" % (vessel.InitialX, wire.CumulativeLength[-1]))

        if abs(clearance) <= 1.0:
            return 0.0

        return clearance
    
    def _eqnVesselAdjust_signedBigTol(vesselX, bigtol):
        
        vessel.InitialX = vesselX
        attempted_vals.append(vesselX)
        mylog.write("Bigger Tolerance, Optimizing with scipy vesselX: %.2f \n" % vessel.InitialX)
        mylog.flush()
                    
        if first_step:
            if vessel.Name == "Vega":
                plet.InitialX = vessel.InitialX - 50
            elif vessel.Name == "Oceans":
                plet.InitialX = vessel.InitialX - 100
            elif vessel.Name == "Navica":
                plet.InitialX = vessel.InitialX - 60
                        
        try: 
            model.CalculateStatics()
            wireAngle = wire.StaticResult("Node declination", objectExtra = of.oeEndA) - 90
            clearance = -1*ramp.InitialRotation2 - wireAngle
            mylog.write("Clearance: %.2f\n" % clearance)
            mylog.flush()
        except:
            mylog.write("Cannot converge with vesselX: %.1f and wire length %.1f\n" % (vessel.InitialX, wire.CumulativeLength[-1]))
            clearance = 0

        if abs(clearance) <= bigtol:
            return 0.0

        return clearance
                  
    try:
        xbounds         = [lowerBoundX, upperBoundX]
        mylog.write(f"Trying with ROOTFINDER first. Bounds: [{lowerBoundX}, {upperBoundX}]\n")
        mylog.flush()
                
        optim           = optimize.root_scalar(_eqnVesselAdjust_signed, bracket=xbounds, method='brentq', xtol=0.5)
        mylog.write(f"optim: {optim} \n")
        mylog.flush()
        vessel.InitialX = optim.root
        attempted_vals.append(optim.root)
        conv_flag = 1
        
        if not optim.converged:
            
            mylog.write("ROOTFINDER has failed to give a solution. Trying a bigger tolerance.\n")
            mylog.flush()
           
            try:
                xbounds         = [lowerBoundX, upperBoundX]
                mylog.write(f"Trying with ROOTFINDER with Bigger Tolerance. Bounds: [{lowerBoundX}, {upperBoundX}]\n")
                mylog.flush()
                optim           = optimize.root_scalar(_eqnVesselAdjust_signedBigTol, bracket=xbounds, method='brentq', xtol=1.0, args=(2.5))
                mylog.write(f"optim: {optim} \n")
                mylog.flush()
                vessel.InitialX = optim.root
                attempted_vals.append(optim.root)
                conv_flag = 1
                
            except:
                failed_filename = '%s-Failed.dat' % (solving_file)
                mylog.write(f"Optim.flag: {optim.flag}")
                mylog.write("ROOTFINDER has failed to give a solution even with bigger tolerance. Saving failed run as %s.\n" % failed_filename)
                mylog.flush()
                model.SaveData(failed_filename)  
                conv_flag = 0
                            
    except:
        # If root scalar fails also. Need to add a condition here if the first guess is too stupid
        try: 
            mylog.write("ROOTFINDER has failed to give a solution. Releasing the frame DOF.\n")
            mylog.flush()
            #modGuessVesselX = upperBoundX + 0.1*wd
            #if plet_clearance < 40:
            #    new_lb = lowerBoundX 
            #else:
            #    new_lb = init_plet_x + 50
            #xbounds         = [new_lb, modGuessVesselX]
            xbounds         = [lowerBoundX, upperBoundX]
            plet.DegreesOfFreedomInStatics = "All"
            optim           = optimize.root_scalar(_eqnVesselAdjust_signed, bracket=xbounds, method='brentq', xtol=0.5)
            mylog.write(f"optim: {optim}\n")
            mylog.flush()
            vessel.InitialX = optim.root    
            attempted_vals.append(optim.root)
            conv_flag = 1
                              
        except:
            try:                
                #
                modGuessVesselX = upperBoundX + 0.1*wd
                if plet_clearance < 40:
                    new_lb = lowerBoundX 
                else:
                    new_lb = init_plet_x + 50 
                xbounds = [new_lb, modGuessVesselX]
                plet.DegreesOfFreedomInStatics = "All"
                mylog.write(f"ROOTFINDER cannot converge with released DOF. Now trying DIFFERENT BOUNDS: [{new_lb},     {modGuessVesselX}].\n")
                mylog.flush()
                optim           = optimize.root_scalar(_eqnVesselAdjust_signed, bracket=xbounds, method='brentq', xtol=0.5)
                mylog.flush()
                vessel.InitialX = optim.root
                attempted_vals.append(optim.root)
                conv_flag = 1
                
            except:
                try:
                    mylog.write("ROOTFINDER with new bounds has failed to give a solution with released DOF. Trying fsolve....\n")
                    mylog.flush()
                    plet.DegreesOfFreedomInStatics = "All"
                    optim, conv_bool, ier, msg     = optimize.fsolve(_eqnVesselAdjust_abs, firstGuessVesselX, xtol = 1e-3, full_output = True)
                    mylog.write(f"ier: {ier} \n" )
                    mylog.flush()
                    conv_flag = 1
                                    
                except:

                    mylog.write("ROOTFINDER with new bounds has failed to give a solution.\n")
                    mylog.flush()
                    
                    try:
                        xbounds         = [lowerBoundX, upperBoundX]
                        mylog.write(f"Trying with ROOTFINDER with Bigger Tolerance. Bounds: [{lowerBoundX}, {upperBoundX}]\n")
                        mylog.flush()
                        optim           = optimize.root_scalar(_eqnVesselAdjust_signedBigTol, bracket=xbounds, method='brentq', xtol=1.0, args=(5.0))
                        mylog.write(f"optim: {optim} \n")
                        mylog.flush()
                        vessel.InitialX = optim.root
                        attempted_vals.append(optim.root)
                        conv_flag = 1
                
                    except:
                        failed_filename = '%s-Failed.dat' % (solving_file)
                        mylog.write("ROOTFINDER has failed to give a solution. Saving failed run as %s.\n" %    failed_filename)
                        mylog.flush()
                        model.SaveData(failed_filename) 
                        conv_flag = 0
    
    print(f"Attempted values: {attempted_vals}")
    mylog.write(f"Attempted values: {attempted_vals} \n")
    
    if conv_flag == 0 and len(attempted_vals) >= 2:   # Simple CLI: guard (IndexError with < 2 attempts)
        vessel.InitialX = attempted_vals[-2]
    
    return model, conv_flag
        
def release_rotationDOF(
    model   : object
    ):
    """
    Function: Redo the model which has been solved with the PLET rotations fixed, now with all DOF released.
    
    Returns: The adjusted model with DOF released.
    """   
    model.CalculateStatics()
    model.UseCalculatedPositions(SetLinesToUserSpecifiedStartingShape=False)
    plet_frame = model["PLET_Frame"]
    plet_frame.DegreesOfFreedomInStatics = "All"
    return model

def continue_sequence_LAND(
    plet_clearance  : float
    ): 
    """
    Function: Check for PLET clearance to see if we remain in the Landing Loop.
    
    Returns: Boolean.
    """ 
    if plet_clearance >=  5 : return True    
    else                    : return False

def continue_sequence_SLACK(
    seabedWireLength    : float
    ): 
    """
    Function: Check for AR wire length resting on seabed to see if we remain in the Slackening Loop.
    
    Returns: Boolean.
    """    
    if seabedWireLength < 5: return True
    else                   : return False
        
def calc_payout(
    line_dict   : dict, 
    payout      : float, 
    clearance   : float, 
    plet_angle  : float
    ):
    
    """
    Function: Takes in current PLET clearance and angle in order to know what the next payout should be.
    
    Returns: Payout. 
    
    """    
    # --- Payout function while PLET has not landed --- #    
    roundown_clearance  = math.floor(clearance)
    max_payout          = line_dict["sequenceGeneral"]["MaxPayoutRate"]
                
    ## Mudmat Wing Opening Zone  # Put condition that mudmat opening cannot be less than 100m clearance, or just remove this altogether
    mudmat_zone         = line_dict["sequenceGeneral"]["MudmatWingOpeningClearance"]
    wd                  = line_dict["sequenceGeneral"]["WD_Max"]    
    hydro_zone          = wd - 100 
    
    flag_hydro  = 0
    flag_mudmat = 0
            
    # --- Hydro Zone --- #    
    if hydro_zone < roundown_clearance:
        
        target_clearance    = hydro_zone
        req_movement        = clearance - target_clearance
        payout              = abs(req_movement/np.sin(np.radians(abs(plet_angle))))
        #
        flag_hydro = 1
        
    # --- Mudmat Zone --- #        
    if mudmat_zone <= roundown_clearance < (mudmat_zone + max_payout):
        
        target_clearance = mudmat_zone  
        
        req_movement = clearance - target_clearance
        payout       = abs(req_movement/np.sin(np.radians(abs(plet_angle))))
        #
        flag_mudmat = 1
                            
    ## Landing Zone
    if (11 < roundown_clearance < (mudmat_zone + 10)) and flag_mudmat == 0:
        
        if 31 < roundown_clearance < (mudmat_zone + 10):
            target_clearance    = 30

        elif 21 < roundown_clearance <= 31:
            target_clearance    = 20

        elif 11 < roundown_clearance <= 21:
            target_clearance    = 10
            
        elif 7 < roundown_clearance <= 11:
            target_clearance = 5
            
        req_movement        = clearance - target_clearance
        payout              = req_movement/np.sin(np.radians(abs(plet_angle)))
        
    elif (0 < roundown_clearance <= 7) and flag_mudmat == 0:
        
        target_clearance    = 0
        req_movement        = clearance - target_clearance
        payout              = req_movement/np.sin(np.radians(abs(plet_angle)))
                   
    else:        
        payout = payout
            
    return max(round(payout), 1)
              
def change_RampAngle(
    tempdict    : dict, 
    line_dict   : dict, 
    customRA    : float
    ):
    '''
    Function: Determines the range of available ramp angles based on vessel type and whether or not custom/minimum ramp angle is to be used, and the next available ramp angle when jacking down.
    
    Returns: The next available ramp angle, the index of this ramp angle in the array of ramp angles.
    '''    
    current_ramp = float(tempdict["Vessel Ramp Angle [deg]"])
    vessel       = str(line_dict["vesselGeneral"].get("VesselSelected"))
    useMinRA     = line_dict["vesselGeneral"].get("UseMinRampAngle")
    minRA        = float(line_dict["vesselGeneral"].get("MinRampAngle"))
    
    if customRA == False:
        ramp_options  = np.array(line_dict["vesselGeneral"].get("RampAngleRange"))
                
    elif customRA == True:
        set_ramp_options     = np.array(line_dict["vesselGeneral"].get("RampAngleRange"))
        gen_ramp_opt         = np.arange(set_ramp_options[0], current_ramp, 1.0)
        ramp_options         = np.unique(np.concatenate((gen_ramp_opt, set_ramp_options)))
        
    if useMinRA == True:
        ramp_options         = ramp_options[ramp_options >= minRA]
            
    #########################################################################################
    if vessel == "Seven Vega" and customRA == True: 
        new_rampangle = current_ramp - 1
        idx_ramp      = np.where(ramp_options < current_ramp)[-1][-1]
    else:      
        try:    
            idx_ramp = np.where(ramp_options < current_ramp)[-1][-1]
        except:
            idx_ramp = 0                
        new_rampangle = ramp_options[idx_ramp]
    
    return new_rampangle, idx_ramp

def move_buoyItems(
    model           : object, 
    plet            : object, 
    has_AR_beam     : bool, 
    buoyConn        : str, 
    tempdict        : dict, 
    line_dict       : dict, 
    AR_beam=None
    ):
    '''
    Function: Move/set the buoy items (buoy, yoke, sling, rigging, triplate) to more favourable positions before solving each static step to aid convergence.
    
    Returns: The model with the aformentioned items modified.
    '''
    
    # Beam Coords, if any
    if has_AR_beam:
        if abs(plet.InitialRotation2) < 45:
            AR_beam.InitialX = plet.InitialX + 50
        else:
            AR_beam.InitialX = float(tempdict["Beam X [m]"]) + 30
        AR_beam.InitialY = float(tempdict["Beam Y [m]"])
        AR_beam.InitialZ = plet.InitialZ + 20
        AR_beam.InitialRotation2 = float(tempdict["PLET Tilt [deg]"]) + 90 
                            
    if buoyConn == "Yoke":
        buoyYokeHinge                    = model["Buoy_Yoke_Hinge"]
        buoyYokeHinge.DOFInitialValue[4] = (90 - abs(plet.InitialRotation2))*-1
        
    no_buoys = int(line_dict["buoyGeneral"]["BuoyancyModuleQuantity"])
    
    slingLength, buoyLength = 0, 0
    
    for i in range(no_buoys):
        buoyItem          = model["Buoyancy_%i" % (i+1)] 
        buoyItem.InitialX = plet.InitialX - 20
        buoyItem.InitialY = 0.0
        slingLength += float(line_dict["buoyGeneral"]["BuoyTable"][i]["SlingLength"])*2   
        buoyLength  += float(line_dict["buoyGeneral"]["BuoyTable"][i]["BuoyLength"])*2      
        buoyItem.InitialZ = plet.InitialZ + line_dict["buoyGeneral"].get("LinkYokeLength") + slingLength + buoyLength
    
    # For some reason, giving a value to triplate starting depth makes things not converge  
    if buoyConn == "Running Wire":
        buoyTriplate            = model["Triplate"]
        buoyFirst               = model["Buoyancy_1"]
        buoyRigging             = model["BuoyRigging_1"]
        buoySling               = model["BuoySling_1"]
        buoyTriplate.InitialX   = buoyFirst.InitialX
        buoyTriplate.InitialY   = 0
        buoyTriplate.InitialZ   = min((buoyFirst.InitialZ - buoyRigging.Length[0]), (plet.InitialZ + 1.2*buoySling.UnstretchedLength) ) 

    return model

def payout_wire_until_land(
    jobpath     : str,
    vessel_json : json,
    basemodel   : any,
    ramp_angle  : float,
    vessel_name : str,
    line_dict   : dict,
    plet_dict   : dict,
    mudmat_dict : dict,
    row         : list,
    mylog       : any
):
    '''
    Function:   This is the main payout sequence function comprising of the landing and the slackening stages.

    '''
    prev_filenum = 4  # This is the number of files generated prior to calling this function
    filenum      = int(line_dict["buoyGeneral"]["BuoyancyModuleQuantity"] + prev_filenum)
         
    if line_dict["vesselGeneral"]["AR_Mode"] == "Dual Mode (A&R Beam)":
        has_AR_beam = True   
    else:
        has_AR_beam = False
        
    buoyConn     = line_dict["buoyGeneral"]["ConnectionType"] 
    AR_conn_type = line_dict["structureGeneral"].get("AR_Type")
       
    payout           = line_dict["sequenceGeneral"]["MaxPayoutRate"]
    new_rampangle    = float(ramp_angle)
    seabedWireLength = 0.0
    plet_clearance   = 100 
    iter             = 0
    #
    last_pletx       = 0
    last_pletz       = 0
    #
    first_payout_postbuoy_flag  = 0
    mudmat_flag                 = 0
    plet_flag                   = 0
    wing_flag                   = 0
    jackdown_flag               = 0
    previous_vesselX            = 0
    conv_flag                   = 1
            
    while continue_sequence_LAND(plet_clearance):
        
        # ------------- While PLET has not LANDED --------- #

        mylog.write("Calculating Static Step %i... \n" % filenum)
        mylog.flush()
            
        newmodel    = of.Model(basemodel)
        ramp_name   = line_dict["vesselGeneral"].get("VesselRamp")
        ramp        = newmodel[ramp_name]
        vessel      = newmodel[vessel_name.capitalize()]
        env         = newmodel["Environment"]
        pipe        = newmodel["Pipe1"]
        wire        = newmodel["Wire1"]
        wd_z        = env.SeabedOriginZ
        if has_AR_beam:
            wire2   = newmodel["Wire2"]
            AR_beam = newmodel["A&R spreader beam"]
        general     = newmodel["General"]
        plet        = newmodel["PLET_Frame"]
        plet.DegreesOfFreedomInStatics = "X,Y,Z"
        pipe.StaticsStep1              = "Catenary"
        try:
            mudmat = newmodel["Mudmat"]
        except:
            pass
        customRA    = line_dict["vesselGeneral"].get("CustomRampAngle")
        #
        if wing_flag == 0: 
            identifier = 1
            ID         = "01"
        else: 
            identifier = 2 
            ID         = "02"
        #
        general.StaticsMaxIterations = 1600
        
        # Change the AR wire length to reflect new payout. Consider moving everything above outside of the loop
                
        if conv_flag == 1:
            read_index = -1
        else:
            read_index = -2
        
        row_last    = row[read_index]
        clearance   = float(row_last["PLET Clearance [m]"])
        plet_angle  = float(row_last["PLET Tilt [deg]"])
        plet_z      = abs(float(row_last["PLET Z [m]"]))
        
        if first_payout_postbuoy_flag == 0:            
            #
            target_clearance    = abs(wd_z) - 100 
            req_movement        = clearance - target_clearance
            payout              = abs(req_movement/np.sin(np.radians(abs(plet_angle))))                   
            first_payout_postbuoy_flag = 1            
        else:  
            default_payout  = line_dict["sequenceGeneral"]["MaxPayoutRate"]  
            payout          = calc_payout(line_dict, default_payout, clearance, plet_angle)
            if conv_flag != 1:
                payout = payout + 20
                       
        try:       
            wire.Length[1]  += payout
            if has_AR_beam:
                wire2.Length[1] += payout
        except:
            mylog.write("AR Wire length adjusted to NEGATIVE. Aborted. \n")
            mylog.flush()
            return row
 
        # Adjust to Mag of Std Err for Lower Clearances ie more pipe touching
        if plet_clearance < 150:
            pipe.FullStaticsConvergenceControlMethod = "Mag. of std. error / change"
            pipe.FullStaticsMinDamping               = 5.0
            pipe.FullStaticsMaxDamping               = 20.0
            pipe.FullStaticsMagOfStdChange           = 0.01
                             
        # Adjust vessel pos to obtain zero lift
        oldvesselX       = vessel.InitialX
        vessel.InitialX += 2.0*payout
        initVesselX      = vessel.InitialX
                
        try: 
            suggested_disp  = np.sin(np.radians(plet_angle))*payout
            plet.InitialZ   = max(-plet_z + suggested_disp, wd_z + 10)
            if vessel.Name == "Vega":
                plet.InitialX = oldvesselX - 50 + payout
            elif vessel.Name == "Oceans":
                plet.InitialX = oldvesselX - 100 + payout
            elif vessel.Name == "Navica":
                plet.InitialX = oldvesselX - 60 + payout
        
        except:
            print(f"Failed to adjust the plet z at step: {filenum}")
            pass
                
        try:
            if has_AR_beam:
                newmodel = move_buoyItems(newmodel, plet, has_AR_beam, buoyConn, tempdict, line_dict, AR_beam)
            else:
                newmodel = move_buoyItems(newmodel, plet, has_AR_beam, buoyConn, tempdict, line_dict)
        except:
            pass
                                
        if plet_clearance  > 5.0:
                        
            saveas          = f"0{filenum}_LD_{ramp_angle}"
            solving_file    = "%s/%s_Stage_%s" % (jobpath, saveas, identifier)
            # Solve with Fixed Rotation
            is_jackingdown             = False  
            newmodel, conv_flag        = solve_WireLift(newmodel, payout, oldvesselX, line_dict, solving_file, oldvesselX, conv_flag, is_jackingdown, mylog)
            unRounded_vesselX          = vessel.InitialX
            vessel.InitialX            = round(vessel.InitialX)
            # Save the intermediate for checking
            solving_file_interm = "%s/%s_Stage_%s-Interm.dat" % (jobpath, saveas, identifier)
            newmodel.SaveData(solving_file_interm) 
            
            # Use Calculated Positions
            try:
                newmodel.CalculateStatics()
            except:
                vessel.InitialX = unRounded_vesselX
                newmodel.CalculateStatics()
                
            newmodel.UseCalculatedPositions(SetLinesToUserSpecifiedStartingShape=False)
            # Free the PLET rotations
            plet.DegreesOfFreedomInStatics = "All"
            plet.InitialRotation1 = 0
            plet.InitialRotation3 = 0
            # Solve again the Wire Lift with Freed Rotation
            mylog.write("Recalculating with Released DOF \n")
            mylog.flush()
            newmodel.CalculateStatics()
            #
            vessel.InitialX = round(vessel.InitialX)
      
        # ------  Adjust PLET initial positions to that of the calculated pos. from previous                
        if iter != 0:
            
            # Ramp
            ramp.InitialRotation2 = -1*new_rampangle
            ramp_angle = new_rampangle
            # PLET coords
            plet.InitialY         = 0
            if plet_clearance > 5.0:
                plet.InitialRotation2 = float(tempdict["PLET Tilt [deg]"])                  
            else:
                plet.InitialRotation2 = 0.0  
                if AR_conn_type == "Yoke":
                    ARYoke_constraint = newmodel["AR_Yoke_Hinge"]
                    ARYoke_constraint.DOFInitialValue[4] = 0.0
            plet.InitialRotation1 = 0
            plet.InitialRotation3 = 0
            
            if has_AR_beam:
                newmodel = move_buoyItems(newmodel, plet, has_AR_beam, buoyConn, tempdict, line_dict, AR_beam)
            else:
                newmodel = move_buoyItems(newmodel, plet, has_AR_beam, buoyConn, tempdict, line_dict)
                                   
        saveas   = f"0{filenum}_LD_{ramp_angle}"
        filename = '%s\%s_Stage_%s.dat' % (jobpath, saveas, identifier)
        newmodel.SaveData(filename)
                
        try:
            static_status    = "-"
            newmodel["General"].Comments = static_status
            wire_presence    = True
            tempdict         = d_extractFunctions.extract_StaticRes(filename, line_dict, ID, static_status, vessel_json,wire_presence)
        except:
            mylog.write("Unable to Extract Result from Static Step. \n")
            mylog.flush()
            static_status = "Previous step did not converge. Manual adjustment needed."
            newmodel["General"].Comments = static_status
                        
            #return row
            pass
                
        # Check of Fixed Ramp Angle of Jack Down at Limit Selected
        # Jack down ramp by 1 step if lcc exceed this
        
        # ---- Read Limits ---- #
        lcc_lim    = float(line_dict["sequenceGeneral"].get("LCC_Limit"))
        strain_lim = float(line_dict["sequenceGeneral"].get("Strain_Limit"))
        stress_lim = float(line_dict["sequenceGeneral"].get("VM_Limit"))
        # ---- Read Values (if possible) ---- #
        maxLCC     = float(tempdict["Pipe Max LCC"])
        maxStress  = float(tempdict["Pipe Max Stress [MPa]"])
        maxStrain  = abs(float(tempdict["Pipe Max Strain [%]"]))
        # ---- Limit Status ---- #
        lcc_lim_status    = line_dict["sequenceGeneral"].get("Use_LCC_Limit")
        stress_lim_status = line_dict["sequenceGeneral"].get("Use_VM_Limit")
        strain_lim_status = line_dict["sequenceGeneral"].get("Use_Strain_Limit")
        #
        plet_clearance_old  = plet_clearance                          # PLET clearance before movement
        plet_clearance      = float(tempdict["PLET Clearance [m]"])   # Intermediate PLET clearance
        plet_angle          = float(tempdict["PLET Tilt [deg]"])
        plet_z              = abs(float(tempdict["PLET Z [m]"]))
        jackdown_status     = line_dict["sequenceGeneral"].get("DeploymentSequenceOption")
        land_status         = line_dict["sequenceGeneral"].get("LandOptNoVesselMove")
               
        # CONDITION 0
        if jackdown_status == "Fixed Ramp Angle":
            allow_jackdown = False
        else:
            allow_jackdown = True 
        
        # CONDITION 1 
        limit_status = " "                       
        if (maxLCC > lcc_lim) and lcc_lim_status: 
            condition_1a = True
            limit_status = "LCC LIMIT"
        else: 
            condition_1a = False
        #
        if (maxStress > stress_lim) and stress_lim_status: 
            condition_1b = True
            limit_status = "STRESS LIMIT"
        else: 
            condition_1b = False
        #
        if (maxStrain > strain_lim) and strain_lim_status: 
            condition_1c = True
            limit_status = "STRAIN LIMIT"
        else: 
            condition_1c = False
        #
        ######
        # CONDITION 1: LIMITS
        if condition_1a or condition_1b or condition_1c: condition_limit = True
        else                                           : condition_limit = False
        # CONDITION 2: PLET LANDING ANGLE
        if abs(plet_angle) >= 25 and plet_clearance <= 15 : condition_2 = True
        else                                              : condition_2 = False        
        # CONDITION 3: PLET CLEARANCE
        if plet_clearance >= 10 : condition_3 = True
        else                    : condition_3 = False
        # CONDITION 4a: PLET NEAR LANDING
        if plet_clearance <= 0.1 and abs(plet_angle) > 0.5 and land_status: condition_4a = True
        else                                                              : condition_4a = False
        # CONDITION 4b: PLET NEAR LANDING
        if plet_clearance <= 0.1 and abs(plet_angle) > 0.5 and not land_status: condition_4b = True
        else                                                                  : condition_4b = False        
        # CONDITION 5: HYDRODYNAMIC PROPERTY CHANGES
        if plet_z >= 99 and plet_flag == 0: condition_5 = True
        else                              : condition_5 = False
        # CONDITION 6: MUDMAT WINGS OPENING UP
        inc_wings           = line_dict["structureGeneral"].get("Mudmat_WingsInc")
        wing_clearance      = line_dict["sequenceGeneral"].get("MudmatWingOpeningClearance")
                
        mylog.write("PLET CLEARANCE PREVIOUS: %.1f, CURRENT: %.1f \n" % (plet_clearance_old, plet_clearance))
        mylog.flush()
        
        if plet_clearance <= wing_clearance and wing_flag == 0 and inc_wings: condition_6 = True
        else                                                                : condition_6 = False
                                                
        if allow_jackdown and (condition_limit or condition_2) and condition_3 and jackdown_flag == 0: 
                                                
            new_rampangle, idx_ramp = change_RampAngle(tempdict, line_dict, customRA)
                            
            mylog.write("Limit(s) Exceeded for Step %i (%s). Lowering ramp to %.1f. Recalculating... \n" % (filenum, limit_status, new_rampangle))
            mylog.flush()
            #
            ramp.InitialRotation2 = -1*new_rampangle
            
            ####### Set AR Wire Len back to previous step so that no payout happens during ramp change
            wire.Length[1]  = wire.Length[1] - payout
            
            if has_AR_beam:
                wire2.Length[1]  = wire2.Length[1] - payout  
                AR_beam.InitialZ = plet.InitialZ + 30   
                plet.InitialRotation2 = min(plet.InitialRotation2, 0.0)      
                        
            ####### -------- Adjusting Vessel Pos -------- ###########
            
            # ---- trying something
            initVesselX = previous_vesselX 
            
            saveas          = f"0{filenum}_LD_{ramp_angle}"
            solving_file    = "%s\%s_Stage_%s" % (jobpath, saveas, identifier)
            # Solve with Fixed Rotation
            plet.DegreesOfFreedomInStatics = "X,Y,Z"
            is_jackingdown              = True
            newmodel, conv_flag         = solve_WireLift(newmodel, payout, initVesselX, line_dict, solving_file, previous_vesselX, conv_flag, is_jackingdown, mylog)
            vessel.InitialX             = round(vessel.InitialX)
            # Save the intermediate for checking
            solving_file_interm = "%s\%s_Stage_%s-Interm.dat" % (jobpath, saveas, identifier)
            newmodel.SaveData(solving_file_interm) 
            # Use Calculated Positions
            newmodel.CalculateStatics()
            newmodel.UseCalculatedPositions(SetLinesToUserSpecifiedStartingShape=False)
            # Free the PLET rotations
            plet.DegreesOfFreedomInStatics = "All"
            plet.InitialRotation1 = 0
            plet.InitialRotation3 = 0
            # Solve again the Wire Lift with Freed Rotation
            newmodel.CalculateStatics()
            #
            vessel.InitialX = round(vessel.InitialX)
                        
            # Flag to stop going into this loop if jacking down is no longer possible
            if idx_ramp == 0: 
                jackdown_flag = 1
                static_status = "CAN NO LONGER JACK DOWN"
            else:
                if condition_limit:
                    static_status = "JACK DOWN to %.1f. %s EXCEEDED." % (new_rampangle, limit_status)
                else:
                    static_status = "JACK DOWN to %.1f. EXCESS PLET TILT." % (new_rampangle)
            
            #
            saveas                          = f"0{filenum}_LD_{new_rampangle}"
            newmodel["General"].Comments    = static_status
            filename                        = '%s\%s_Stage_%s.dat' % (jobpath, saveas, identifier)
            newmodel.SaveData(filename)
                
            wire_presence                   = True    
            tempdict = d_extractFunctions.extract_StaticRes(filename, line_dict, "01", static_status, vessel_json, wire_presence) 
            
        if condition_4a:
                       
            static_status = "PLET HAS TOUCHED SEABED. VESSEL STATIONARY."
            mylog.write("PLET has touched the seabed. Paying out wire WITHOUT moving vessel to fully settle. PLET Tilt: %.1f \n" % plet_angle)
            mylog.flush()
            # ---- Payout Data ---- #
            payout           = 5
            wire.Length[1]  += payout
            if has_AR_beam:
                wire2.Length[1]  += payout
            
            # ---- Move Vessel Back --- #
            vessel.InitialX = float(row[-1]['Vessel X [m]'])
            
            # ---- Naming Convention Data
            current_ramp                    = float(tempdict["Vessel Ramp Angle [deg]"])
            saveas                          = f"0{filenum}_LD_{current_ramp}"
            newmodel["General"].Comments    = static_status
            filename                        = '%s\%s_Stage_%s.dat' % (jobpath, saveas, identifier)
            newmodel.SaveData(filename)
            #
            # Simple CLI: argument order fixed (vessel_json/static_status were swapped) and wire flag added
            tempdict = d_extractFunctions.extract_StaticRes(filename, line_dict, "01", static_status, vessel_json, True)
            #
            plet_clearance      = float(tempdict["PLET Clearance [m]"])
            plet_angle          = float(tempdict["PLET Tilt [deg]"])
                    
        if condition_4b:
            
            static_status = "PLET HAS TOUCHED SEABED. VESSEL MOVED."            
            mylog.write("PLET has touched the seabed. Paying out wire AND move vessel to fully settle. PLET Tilt: %.1f \n" % plet_angle)
            mylog.flush()
            # ---- Payout Data ---- #
            payout           = 20
            wire.Length[1]  += payout
            if has_AR_beam:
                wire2.Length[1]  += payout
            
            if AR_conn_type == "Yoke":
                ARYoke_constraint = newmodel["AR_Yoke_Hinge"]
                ARYoke_constraint.DOFInitialValue[4] = 0.0
            
            ####### -------- Adjusting Vessel Pos -------- ###########
            initVesselX             = vessel.InitialX
            plet.InitialZ           = wd_z + 10
            plet.InitialRotation2   = 0.0
            #
            saveas                          = f"0{filenum}_LD_{ramp_angle}"
            newmodel["General"].Comments    = static_status
            solving_file                    = "%s/%s_Stage_%s" % (jobpath, saveas, identifier)
            
            is_jackingdown              = False
            newmodel, conv_flag         = solve_WireLift(newmodel, payout, initVesselX, line_dict, solving_file, initVesselX, conv_flag, is_jackingdown, mylog)                    
            vessel.InitialX             = round(vessel.InitialX)
            
            # ---- Naming Convention Data
            current_ramp  = float(tempdict["Vessel Ramp Angle [deg]"])
            saveas        = f"0{filenum}_LD_{current_ramp}"
            filename      = '%s\%s_Stage_%s.dat' % (jobpath, saveas, identifier)
            newmodel.SaveData(filename)
            #
            wire_presence   = True
            tempdict        = d_extractFunctions.extract_StaticRes(filename, line_dict, "01", static_status, vessel_json, wire_presence) 
            #
            plet_clearance      = float(tempdict["PLET Clearance [m]"])
            plet_angle          = float(tempdict["PLET Tilt [deg]"])
                    
        if condition_5:
        
            static_status = "PLET switched over to Deep Zone Properties."
            
            # ---- Save model with surface hydro properties first ---- #
            current_ramp  = float(tempdict["Vessel Ramp Angle [deg]"])
            newmodel["General"].Comments = "PLET with Surface Hydrodynamic Properties"
            saveas        = f"0{filenum}_LD_{current_ramp}"
            filename      = '%s\%s_Stage_%s-SurfaceHydro.dat' % (jobpath, saveas, identifier)
            newmodel.SaveData(filename)
            
            # ---- Switch Over to Deep PLET Properties ---- #
            mylog.write("PLET has reached deep zone. Recalculate for deep zone PLET properties. \n")
            mylog.flush()
            plet.DragForceCoefficientX = plet_dict['cd_deep_x']
            plet.DragForceCoefficientY = plet_dict['cd_deep_y']
            plet.DragForceCoefficientZ = plet_dict['cd_deep_z']
            plet.DragAreaMomentX       = plet_dict['drag_moment_area_deep_x']
            plet.DragAreaMomentY       = plet_dict['drag_moment_area_deep_y']
            plet.DragAreaMomentZ       = plet_dict['drag_moment_area_deep_z']
            try:
                # DO MUDMAT STUFF HERE
                mudmat.DragForceCoefficientX = mudmat_dict['cd_deep_x']
                mudmat.DragForceCoefficientY = mudmat_dict['cd_deep_y']
                mudmat.DragForceCoefficientZ = mudmat_dict['cd_deep_z']
                mudmat.DragAreaMomentX       = mudmat_dict['drag_moment_area_deep_x']
                mudmat.DragAreaMomentY       = mudmat_dict['drag_moment_area_deep_y']
                mudmat.DragAreaMomentZ       = mudmat_dict['drag_moment_area_deep_z']
            except:
                pass
            # ---- Naming Convention Data --- #
            current_ramp                    = float(tempdict["Vessel Ramp Angle [deg]"])
            newmodel["General"].Comments    = "PLET with Deep Zone Hydrodynamic Properties"
            saveas                          = f"0{filenum}_LD_{current_ramp}"
            filename                        = '%s\%s_Stage_%s.dat' % (jobpath, saveas, identifier)
            newmodel.SaveData(filename)
            #
            wire_presence    = True
            tempdict         = d_extractFunctions.extract_StaticRes(filename, line_dict, "01", static_status, vessel_json, wire_presence) 
            #
            plet_clearance      = float(tempdict["PLET Clearance [m]"])
            plet_angle          = float(tempdict["PLET Tilt [deg]"])
            #
            plet_flag = 1
                                               
        if condition_6: 
            # ------ Switch to Separate Frame/Mudmat for when the Mudmat Wings are Down
            # - No wire payout when opening mudmat
            # - No vessel movement when opening mudmat
            static_status = "REACHED CLEARANCE TO OPEN MUDMAT WINGS: %.1f." % plet_clearance
            mylog.write("MUDMAT WINGS OPENED, PLET CLEARANCE %.2f. \n" % plet_clearance)
            mylog.flush()
            
            ## Fetch necessary items from previous model
            oldmodel         = of.Model(filename)
            vessel_locX      = vessel.InitialX
            # pipe lengths
            arr_pipelen      = []
            for idx in range(6):
                arr_pipelen.append(pipe.Length[idx])
                
            wire_len_sec0    = oldmodel["Wire1"].Length[0] 
            wire_len_sec1    = oldmodel["Wire1"].Length[1] 
            if has_AR_beam:
                wire2_len_sec0   = oldmodel["Wire2"].Length[0] 
                wire2_len_sec1   = oldmodel["Wire2"].Length[1]
            else:
                try:
                    oldmodel.DestroyObject("Wire2")
                    oldmodel.DestroyObject("Wire3")
                except:
                    pass
            ramp_angle  = ramp.InitialRotation2 
            plet_locX   = plet.InitialX
            plet_locZ   = plet.InitialZ
            plet_angle  = plet.InitialRotation2
            
            # Set to this to aid convergence
            pipe.FullStaticsConvergenceControlMethod = "Mag. of std. error / change"
            pipe.FullStaticsMinDamping               = 5.0
            pipe.FullStaticsMaxDamping               = 20.0
            pipe.FullStaticsMagOfStdChange           = 0.01
            
            # Save OldModel at this step as Step n
            saveas        = f"0{filenum}_LD_{current_ramp}"
            oldfilename   = '%s\%s_Stage_%s.dat' % (jobpath, saveas, "1") #identifier
            oldmodel.SaveData(oldfilename)
            
            wire_presence    = True
            tempdict = d_extractFunctions.extract_StaticRes(oldfilename, line_dict, "01", static_status, vessel_json, wire_presence)
            #
            row.append(tempdict)
                       
            ## Load New Model from Previously Saved File, Stage_2_PLET.dat  
            mylog.write("Pick up base file from %s\Stage_2_PLET.dat \n" % jobpath)         
            newmodel   = of.Model("%s\Stage_2_PLET.dat" % jobpath)
            # Model Fudging to aid Convergence
            newmodel["General"].ImplicitUseVariableTimeStep = 'Yes'
            newmodel["General"].StaticsMinDamping = 5  
            newmodel["General"].StaticsMaxDamping = 20
            newmodel["General"].ImplicitVariableMaxTimeStep = 0.05
            newmodel["General"].ImplicitVariableMaxNumOfIterations = 100
            newmodel["General"].Comments = static_status
            #
            ramp_name  = line_dict["vesselGeneral"].get("VesselRamp")
            ramp       = newmodel[ramp_name]
            vessel     = newmodel[vessel_name.capitalize()]
            pipe       = newmodel["Pipe1"]   
            # Set New Pipelengths
            for idx in range(6):
                if line_dict["SJGeneral"].get("SJrequired") == False:
                    pipe.Length[idx] = arr_pipelen[idx]
                else:
                    if idx != 1:
                        pipe.Length[idx] = arr_pipelen[idx]
                
            wire       = newmodel["Wire1"]
            if has_AR_beam:
                wire2       = newmodel["Wire2"]
            else:
                try:
                    newmodel.DestroyObject("Wire2")
                    newmodel.DestroyObject("Wire3")
                except:
                    pass
            plet       = newmodel["PLET_Frame"]
                        
            # Adjust the Vessel and Pipe/Wire Parameters
            vessel.InitialX         = vessel_locX
            wire.Length[0]          = wire_len_sec0
            wire.Length[-1]         = wire_len_sec1 #float(row[-1]["Wire1 Length [m]"]) - wire_len_sec0 + payout
            #
            if has_AR_beam:
                wire2.Length[0]          = wire2_len_sec0
                wire2.Length[-1]         = wire2_len_sec1 #float(row[-1]["Wire2 Length [m]"]) - wire2_len_sec0 + payout
            #
            ramp.InitialRotation2   = ramp_angle
            plet.InitialX           = plet_locX
            plet.InitialZ           = plet_locZ
            plet.InitialRotation2   = plet_angle
            
            # Set to this to aid convergence
            pipe.FullStaticsConvergenceControlMethod = "Mag. of std. error / change"
            pipe.FullStaticsMinDamping               = 5.0
            pipe.FullStaticsMaxDamping               = 20.0
            pipe.FullStaticsMagOfStdChange           = 0.01
                        
            # Adjust the Triplate and Buoy Locations if applicable
            conn_type = line_dict["buoyGeneral"].get("ConnectionType")
            
            if conn_type == "Yoke":
                newbuoyYokeHinge                    = newmodel["Buoy_Yoke_Hinge"]       
                newbuoyYokeHinge.DOFInitialValue[4] = (90 - abs(plet.InitialRotation2))*-1
                
            elif conn_type == "Running Wire":
                triplate            = newmodel["Triplate"]
                triplate.IncludedInStatics = "Yes"
                slingLength         = float(line_dict["buoyGeneral"].get("LinkYokeLength"))
                triplate.InitialZ   = plet.InitialZ + 1.5*slingLength
                                
            # Add Buoy(s) and Rigging(s)
            no_buoys = line_dict["buoyGeneral"].get("BuoyancyModuleQuantity")
            for buoyID in range(no_buoys):
                oldRigLT   = oldmodel["BuoyRigType_%i" % (buoyID+1)]
                oldBuoyObj = oldmodel["Buoyancy_%i" % (buoyID+1)]
                oldRigObj  = oldmodel["BuoyRigging_%i" % (buoyID+1)]
                
                oldRigObj.LineType[0] = "BuoyRigType_%i" % (buoyID+1)
                    
                clone = oldBuoyObj.CreateClone(model=newmodel)
                clone = oldRigObj.CreateClone(model=newmodel)
                clone = oldRigLT.CreateClone(model=newmodel)
                                                
                if conn_type == "Running Wire":
                    triplate    = oldmodel["Triplate"] 
                    triplate.IncludedInStatics = "Yes"
                    oldBuoyObj.InitialZ = triplate.InitialZ + 1.2*oldRigObj.Length[0]*(buoyID + 1)
                    
                elif conn_type == "Yoke":
                    pletBuoyAttach = oldmodel["PLET_BuoyAttach"]
                    oldBuoyObj.InitialZ = pletBuoyAttach.InitialZ + 1.2*oldRigObj.Length[0]*(buoyID + 1)
                    
            for buoyID in range(no_buoys):
                newRigLT   = newmodel["BuoyRigType_%i" % (buoyID+1)]
                newRigObj  = newmodel["BuoyRigging_%i" % (buoyID+1)]
                
                newRigObj.LineType[0] = "BuoyRigType_%i" % (buoyID+1)
                
            riggingObj1 = newmodel["BuoyRigging_1"]
                                                       
            # Naming Convention Data
            current_ramp                    = float(tempdict["Vessel Ramp Angle [deg]"])
            newmodel["General"].Comments    = "MUDMAT WINGS OPENED."
            saveas                          = f"0{filenum+1}_LD_{current_ramp}"
            filename                        = '%s\%s_Stage_%s.dat' % (jobpath, saveas, "2")   
            
            # ------ Free Up the PLET ------------------------- #
            newmodel.SaveData(filename)
            #
            plet_clearance      = float(tempdict["PLET Clearance [m]"])
            plet_angle          = float(tempdict["PLET Tilt [deg]"])
            #
            static_status = "MUDMAT WINGS OPENED AT SEABED CLEARANCE %.1f." % plet_clearance
            static_stepcount = filenum + 1
            wire_presence    = True
            tempdict = d_extractFunctions.extract_StaticRes(filename, line_dict, "02", static_status, vessel_json, wire_presence) 
            #
            wing_flag = 1
            filenum  += 1
            
            mylog.flush()
                
        row.append(tempdict)
        filenum += 1
        plet_clearance      = float(tempdict["PLET Clearance [m]"])
        plet_angle          = float(tempdict["PLET Tilt [deg]"])
        plet_z              = abs(float(tempdict["PLET Z [m]"]))
        basemodel           = filename 
        
        payout              = calc_payout(line_dict, payout, plet_clearance, plet_angle)           
        previous_vesselX    = vessel.InitialX
                                                    
        mylog.write("PLET Clearance: %.2f, Next Payout: %.2f \n" % (tempdict["PLET Clearance [m]"], payout))
        mylog.write("------------------------------------------- \n")
        mylog.flush()
        
        iter += 1
   
    # --- End of Landing Loop, beginning the Slackening Loop --- #
    # --- Pickup Last PLET Position
    last_pletx       = plet.InitialX
    last_pletz       = plet.InitialZ
             
    ## New Model Definition (Just for Paying out Wire)    
    basemodel   = filename
    newmodel    = of.Model(basemodel)
    ramp_name   = line_dict["vesselGeneral"].get("VesselRamp")
    ramp        = newmodel[ramp_name]
    vessel      = newmodel[vessel_name.capitalize()]
    plet        = newmodel["PLET_Frame"]
    env         = newmodel["Environment"]
    pipe        = newmodel["Pipe1"]
    wire        = newmodel["Wire1"]
    if has_AR_beam:
        beam         = newmodel["A&R spreader beam"]
        wire2        = newmodel["Wire2"]
    general     = newmodel["General"]
    general.StaticsMaxIterations   = 1600
    plet.DegreesOfFreedomInStatics = "All"
    #
    slack_iter       = 0
    seabedWireLength = 0
                        
    while continue_sequence_SLACK(seabedWireLength):
        
        # ------------- While PLET has LANDED, payout wire to slacken --------- #
        plet.InitialZ           = last_pletz 
        plet.InitialRotation2   = 0.0
        plet.InitialX           = last_pletx 
        
        pipe.FullStaticsConvergenceControlMethod = "Mag. of std. error / change"
        pipe.FullStaticsMinDamping               = 5.0
        pipe.FullStaticsMaxDamping               = 20.0
        pipe.FullStaticsMagOfStdChange           = 0.01
                
        ###### -------- Set PLET Initial WD ---- #                    
        if slack_iter == 0 or slack_iter == 1: 
            payout = 100
        else: 
            payout = 25
                    
        mylog.write("Slackening the AR wire by paying out %i m. Total wire length: %.1f m \n" % (payout, wire.CumulativeLength[-1]) )
        mylog.write("Wire length resting on seabed: %.1f\n" % seabedWireLength)
        mylog.flush()
             
        wire.Length[1]  += payout
        
        if has_AR_beam:
            wire2.Length[1]        += payout
            beam.InitialZ           = plet.InitialZ + 5
            beam.InitialX           = plet.InitialX + payout + 10  # check this
            beam.InitialRotation2   = 90.0
            
        # Adjust the AR Yoke angle if applicable
        AR_conn_type = line_dict["structureGeneral"].get("AR_Type")
        if AR_conn_type == "Yoke":
            ARYoke_constraint = newmodel["AR_Yoke_Hinge"]
            ARYoke_constraint.DOFInitialValue[4] = 0.0
            
        # Adjust the Triplate and Buoy Locations if applicable
        conn_type = line_dict["buoyGeneral"].get("ConnectionType")
            
        if conn_type == "Yoke":
            newbuoyYokeHinge                    = newmodel["Buoy_Yoke_Hinge"]       
            newbuoyYokeHinge.DOFInitialValue[4] = -1*(90 - abs(plet.InitialRotation2))
                
        elif conn_type == "Running Wire":
            triplate            = newmodel["Triplate"]
            slingLength         = float(line_dict["buoyGeneral"].get("LinkYokeLength"))
            triplate.InitialZ   = plet.InitialZ + 3*slingLength 
            triplate.InitialX   = plet.InitialX
            
        # Add Buoy(s) and Rigging(s)
        no_buoys = line_dict["buoyGeneral"].get("BuoyancyModuleQuantity")
        for buoyID in range(no_buoys):
            BuoyObj = newmodel["Buoyancy_%i" % (buoyID+1)]
            RigObj  = newmodel["BuoyRigging_%i" % (buoyID+1)]
            
            if conn_type == "Running Wire":
                triplate.IncludedInStatics = "Yes"
                BuoyObj.InitialZ = triplate.InitialZ + 1.2*RigObj.Length[0]*(buoyID + 1)
            elif conn_type == "Yoke":
                pletBuoyAttach   = newmodel["PLET_BuoyAttach"]
                BuoyObj.InitialZ = plet.InitialZ + 10 + 1.2*RigObj.Length[0]*(buoyID + 1) + 1.5*BuoyObj.Height*(buoyID + 1)
            
            BuoyObj.InitialX = plet.InitialX
                            
        ####### -------- Adjusting Vessel Pos -------- ########### 
        initVesselX     = vessel.InitialX + payout
        saveas          = f"0{filenum}_LD_{ramp_angle}"
        solving_file    = "%s/%s_Stage_%s" % (jobpath, saveas, identifier) 
        plet.DegreesOfFreedomInStatics = "All"
        
        is_jackingdown             = False
        newmodel, conv_flag        = solve_WireLift(newmodel, payout, initVesselX, line_dict, solving_file, vessel.InitialX, conv_flag, is_jackingdown, mylog)
        vessel.InitialX            = round(vessel.InitialX)
        #
        if wing_flag == 0: 
            identifier = 1
            ID         = "01"
        else:
            identifier = 2
            ID         = "02"
            
        current_ramp                    = float(tempdict["Vessel Ramp Angle [deg]"])
        static_status                   = "PLET LANDED. SLACKENING WIRE."
        newmodel["General"].Comments    = static_status
        saveas                          = f"0{filenum}_LD_{current_ramp}"
        filename                        = '%s\%s_Stage_%s.dat' % (jobpath, saveas, identifier)
                
        newmodel.SaveData(filename)
        #
        wire_presence    = True 
        tempdict         = d_extractFunctions.extract_StaticRes(filename, line_dict, ID, static_status, vessel_json, wire_presence)
        #
        seabedWireLength = float(tempdict["Wire Length on Seabed [m]"])
        #
        slack_iter += 1
        
    row.append(tempdict)
                
    return row
            
def deploy_buoy(
    jobpath,
    vessel_json,
    basemodel,
    ramp_angle,
    vessel_name,
    wireline, 
    line_dict,
    row,
    mylog
): 
    '''
    Function:   Deploy 1 buoy per step. Adjust the wire length based on the min WD needed to fully submerge the deployed buoys.
                Wire lift optimisation performed with fixed PLET rotations, which are then freed, and the statics recalculated.
                Extract results into tempdict. Appended into 'row', which is a list containing all the results.
                
    Returns :   Row, with the results from the buoy steps appended.           
    ''' 
        
    def _solve_wireLift(vesselX):
        
        vessel.InitialX = vesselX
        mylog.write("Optimising wire lift: Vessel Pos: %.3f m \n" % vessel.InitialX)
        mylog.flush()
        
        try:
            newmodel.CalculateStatics()
            wireAngle = wire.StaticResult("Node declination", objectExtra = of.oeEndA) - 90
            clearance = abs(-1*ramp.InitialRotation2 - wireAngle)
            
        except:
            mylog.write("Statics failed at wire lift calc. Please check the buoy settings. \n") 
            mylog.flush()          
            datname         = f"0{stepIndex+1}_LD_{ramp_angle}"   # buoy activation
            failed_filename = "%s/%s_Stage_%s-Failed.dat" % (jobpath, datname, "1")
            
            newmodel.SaveData(failed_filename)
            clearance = 0
            
        if clearance <= 0.1:
            return 0.00
        
        return clearance     
    
    def _calc_buoyVolume(uplift, mass, seawater_rho):
        vol = (mass - -1*uplift)/float(seawater_rho)
        return vol 
                
    prev_filenum = 4  # Steps created prior to this function
    mylog.write("Creating Buoyancy Module Steps... \n")
    mylog.flush()
        
    # Generally Used Items
    rho_sw           = line_dict["General"].get("Seawater_density")        
    useBuoy          = line_dict["buoyGeneral"].get("UseBuoyancy")   
    Buoy_PLET_attach = line_dict["buoyGeneral"].get("ConnectionType")
    
    if line_dict["vesselGeneral"].get("AR_Mode") == "Dual Mode (A&R Beam)":
        has_AR_beam = True
    else:
        has_AR_beam = False
    
    # Get Buoy Dictionary    
    buoyDict         = line_dict["buoyGeneral"].get("BuoyTable")
    buoyNames        = []
    riggingNames     = []
    riggingLinetypes = []
    len_buoy_rigs    = 0
    
    len_wireinit = wireline.Length[0]
    
    # Note that for autoPayout, basemodel is always basemodel, only the wire payout changes
    # In the case of different Buoyancy Number, need to have 1 base model, and then for the following steps
    # Add different number of buoys to the base model
    
    for stepIndex in range(len(buoyDict)):
        
        buoyStepIndex                   = stepIndex + prev_filenum
        
        mylog.write(f"----- Step 0{buoyStepIndex} ------ \n")
        mylog.write(f"...Creating Buoy Deployment Step (Buoy {stepIndex + 1} of {len(buoyDict)}) for Ramp Angle {ramp_angle} \n")
        mylog.flush()
        
        # ----- Create New Model copied from previous step -------- #
        
        newmodel    = of.Model(basemodel)  
        ramp_name   = line_dict["vesselGeneral"].get("VesselRamp")
        ramp        = newmodel[ramp_name]
        vessel      = newmodel[vessel_name.capitalize()]
        plet_frame  = newmodel["PLET_Frame"]
        wire        = newmodel["Wire1"]
        if has_AR_beam:
            wire2   = newmodel["Wire2"]
        general     = newmodel["General"]
        general.StaticsMaxIterations = 1200
        plet_frame.DegreesOfFreedomInStatics = "X,Y,Z"
                
        subBuoyDict = buoyDict[0:stepIndex+1]
        
        len_buoy_rigs = 0
                
        for buoyIndex, buoyItem in enumerate(subBuoyDict):
                    
            # Create Buoy(s)
            buoyID     = buoyItem.get("BuoyID")
            buoyUplift = buoyItem.get("BuoyUplift")
            newBuoyObj = newmodel.CreateObject(of.ot3DBuoy, "Buoyancy_%i" % buoyID)
            newBuoyObj.Mass   = buoyItem.get("BuoyWeight")
            newBuoyObj.Volume = _calc_buoyVolume(buoyUplift, buoyItem.get("BuoyWeight"), rho_sw)
            newBuoyObj.Height = buoyItem.get("BuoyLength")
            # Hydro Properties
            buoy_width    = 1
            buoy_length   = newBuoyObj.Volume/(buoy_width * newBuoyObj.Height)
            BuoyHydroDict = b_builderFunctions.calc_hydro_properties_buoyancy_module(buoy_width, buoy_length, newBuoyObj.Height)
            newBuoyObj.DragAreaX = BuoyHydroDict["dragAreaX"]
            newBuoyObj.DragAreaY = BuoyHydroDict["dragAreaY"]
            newBuoyObj.DragAreaZ = BuoyHydroDict["dragAreaZ"]
            newBuoyObj.CdX       = BuoyHydroDict["cdX"]
            newBuoyObj.CdY       = BuoyHydroDict["cdY"]
            newBuoyObj.CdZ       = BuoyHydroDict["cdZ"]
            newBuoyObj.CaX       = BuoyHydroDict["caX"]
            newBuoyObj.CaY       = BuoyHydroDict["caY"]
            newBuoyObj.CaZ       = BuoyHydroDict["caZ"]
            
            buoyNames.append(newBuoyObj)
        
            # Create Buoy Rigging Linetypes
            rig_LTobj    = newmodel.CreateObject(of.otLineType, "BuoyRigType_%i" % buoyID)
            rig_LTobj.OD = buoyItem.get("SlingOD")/1000.
            rig_LTobj.ID = 0.0
            rig_LTobj.MassPerUnitLength = buoyItem.get("SlingMass")
            rig_LTobj.EA = 41.37E3
            rig_LTobj.GJ = 80.0
            rig_LTobj.PenColour = 0xC0C0C0
            riggingLinetypes.append(rig_LTobj) 
        
            # Create Buoy Rigging             
            riggingObj = newmodel.CreateObject(of.otLine, "BuoyRigging_%i" % buoyID)
            riggingObj.LineType[0]              = "BuoyRigType_%i" % buoyID
            riggingObj.Length[0]                = buoyItem.get("SlingLength")
            riggingObj.TargetSegmentLength[0]   = 2.0
            riggingObj.StaticsSeabedFrictionPolicy = "None"
            riggingObj.EndAConnection = "Buoyancy_%i" % buoyID
            riggingObj.EndAX, riggingObj.EndAY, riggingObj.EndAZ = [0, 0, 0] 
            if buoyID == 1:
                if Buoy_PLET_attach == "Running Wire":
                    riggingObj.EndBConnection = "Triplate"
                elif Buoy_PLET_attach == "Yoke":
                    riggingObj.EndBConnection = "PLET_BuoyAttach"
                riggingObj.EndBDeclination = 90.0
            else:
                riggingObj.EndBConnection = "Buoyancy_%i" % (buoyID - 1)
            riggingObj.EndBX, riggingObj.EndBY, riggingObj.EndBZ = [0, 0, 0]             
            riggingNames.append(riggingObj)

            ################################
            
            if Buoy_PLET_attach == "Running Wire":
                triplate    = newmodel["Triplate"] 
                triplate.IncludedInStatics = "Yes"
                initPos1    = triplate.InitialZ

            elif Buoy_PLET_attach == "Yoke":
                initPos1    = plet_frame.InitialZ + 2*line_dict["buoyGeneral"].get("LinkYokeLength")

            if buoyIndex == 0: 
                init_buoyPos        = initPos1 + 2*buoyDict[buoyIndex].get("SlingLength")
                newBuoyObj.InitialZ = init_buoyPos
                current_pos         = init_buoyPos

            else:
                newBuoyObj.InitialZ = current_pos + buoyDict[buoyIndex].get("BuoyLength") + buoyDict[buoyIndex].get ("SlingLength")
                current_pos = newBuoyObj.InitialZ

            newBuoyObj.InitialX   = plet_frame.InitialX - 2
            newBuoyObj.InitialY   = plet_frame.InitialY

            len_buoy_rigs += buoyDict[buoyIndex].get("SlingLength") + buoyDict[buoyIndex].get("BuoyLength")
            
        # Calculate min WD needed to deploy all buoyancy modules
        len_yokesling  = line_dict["buoyGeneral"].get("LinkYokeLength")  
        wire.Length[0] = round(len_yokesling + len_wireinit + len_buoy_rigs)
        if has_AR_beam:
            wire2.Length[0] = wire.Length[0]
            
        # -------- Save Snapshot per 1 Buoy Deployed ------ #    
        datname                         = f"0{buoyStepIndex}_LD_{ramp_angle}"   # buoy activation
        static_status                   = "%i BUOY(S) DEPLOYED" % (buoyStepIndex - 3)
        newmodel["General"].Comments    = static_status
        filename                        = "%s\%s_Stage_%s.dat" % (jobpath, datname, "1")
                    
        # -------- Adjust Wire Lift ----------------------- #
        initVesselX  = vessel.InitialX
        plet_frame.DegreesOfFreedomInStatics = "X,Y,Z"   
        optim        = optimize.fsolve(_solve_wireLift, initVesselX, xtol = 1e-3, full_output = True)
        
        # ------ Round Up/Down Vessel Movement ------------ #
        vessel.InitialX = round(vessel.InitialX)
        
        # ------ Free Up the PLET ------------------------- #
        newmodel = release_rotationDOF(newmodel)
        newmodel.CalculateStatics()        
        newmodel.SaveData(filename)
        mylog.write(f"Saving Step0{buoyStepIndex} - {buoyStepIndex - 3} Buoyancy Module(s) deployed \n")
        mylog.flush()
        #
        wire_presence = True
        tempdict = d_extractFunctions.extract_StaticRes(filename, line_dict, "01", static_status, vessel_json, wire_presence)
        row.append(tempdict)
                
    return row
        