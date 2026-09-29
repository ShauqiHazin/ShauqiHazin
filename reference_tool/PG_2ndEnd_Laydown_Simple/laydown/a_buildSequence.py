import os
import json
import math
import time
import OrcFxAPI as of

from . import utils
from . import constants
from . import b_builderFunctions
from . import c_sequenceFunctions
from . import d_extractFunctions

from scipy import optimize
import numpy as np
import pandas as pd

'''
Script      :   a_buildSequence.py

Function    :   Contains functions that serve the following purposes:
                * create the basic first 4 steps (tensioner step, clamp step, pallet step, first submerged step)
                * call the buoyancy module deployment step builder
                * call the sequence builder
                
Dependents  :   * UI_func.py
                
Last update :   22 April 2026
Author      :   S.O
'''

def move_PLET_10m(
    model       : object, 
    line_dict   : dict
):  ## Will reabsorb this somewhere else
    '''
    Functions   :   Move the PLET to 10m WD for the first submerged step
    
    Args        :   -model (the model in question)
                    -line_dict (the job dict)
    
    Returns     : -
    '''        
    plet_frame                   = model['PLET_Frame']
    rampName                     = line_dict["vesselGeneral"].get("VesselRamp")
    ramp                         = model[rampName]
        
    # PLET Initial Location - set to about 10m WD
    plet_frame.InitialRotation2  = -1*float(line_dict["vesselGeneral"].get("SelectedRampAngle"))
    plet_frame.InitialX          = ramp.InitialX - float(line_dict["structureGeneral"].get("Frame_Height")) - 10
    plet_frame.InitialZ          = -10
                 
def create_static_sequence(
    jobpath     : str,
    vessel_name : str,   
    vessel_json : json,    
    model       : object, 
    model_cl    : object, 
    model_pal   : object,  
    line        : object,
    wireline1   : object,
    line_dict   : dict,
    plet_dict   : dict,
    mudmat_dict : dict,
    baseOnly    : str,
    mylog       : any
):
    '''
    Function    :   *Create the first 4 steps in-house (00 NL tensioner, 01 NL clamp, 02 Structure on pallet, 03 PLET just submerged)
                    *Calls on functions deploy_buoy and payout_wire_until_land to complete the whole landing sequence.
                    *Calls on the extract results function to do the raw results table.
                    *Calls on the laytable function to produce formatted laytable.
                    
    Args        :   -jobpath (string containing the job directory)
                    -vessel_name (shortened vessel name, sans 'Seven', in lowercase)
                    -vessel_json (vessel dict)
                    -model (the model, main)
                    -model (the model, used for the clamped and tensioner step)
                    -model (the model, used for the pallet step)
                    -line (the pipe line)
                    -wireline1 (the ar wire)
                    -line_dict (the job dict)
                    -plet_dict (plet dictionary)
                    -mudmat_dict (mudmat dict)
                    -baseOnly ('YES' or 'NO', if 'YES' then won't call payout_wire, so that user can check model before full sequence)
                    -mylog (logfile)
                                        
    Returns     :   -
    ''' 
    
    def _setZeroBM_pipeLen(pipelen: float):
        
        print(f"pipelen: {pipelen}")
        line_cl.Length[4] = np.sqrt(abs(pipelen))
        mylog.write(f"Optimising pipe length wrt to BM: Pipe section: {line_cl.Length[4]} m \n")
        mylog.flush()

        try:
            model_cl.CalculateStatics()
            bendMoment = line_cl.StaticResult("In plane bend moment", objectExtra = of.oeEndA)

        except:
            mylog.write("Statics failed at wire lift calc \n")
            model_cl.SaveData(os.path.join(jobpath, "Static-Failed.dat"))
            # Simple CLI: a failed solve must not look like a root (was 0)
            bendMoment = 1.0e6
                    
        if abs(bendMoment) <= 1.0:
            return 0.00
        
        return bendMoment
    
    def _setzeroBM_vesselX(vesselX: float):
        
        vessel_cl.InitialX = vesselX
        
        mylog.write("Optimizing with scipy vesselX: %.3f \n" % vessel_cl.InitialX)
        mylog.flush()

        try: 
            model_cl.CalculateStatics()
            bendMoment = line_cl.StaticResult("In plane bend moment", objectExtra = of.oeEndA)
        except:
            mylog.write("Cannot converge with vesselx: %.1f \n" % vessel_cl.InitialX)
            model_cl.SaveData(os.path.join(jobpath, "Static-Failed.dat"))
            mylog.flush()
            # Simple CLI: a failed solve must not look like a root (was 0)
            bendMoment = 1.0e6

        if abs(bendMoment) <= 1.0:
            return 0.0

        return bendMoment
            
    row         = []
       
    jobID       = line_dict["General"].get("jobID")
    ramp_angle  = line_dict["vesselGeneral"].get("SelectedRampAngle")
    ramp_name   = line_dict["vesselGeneral"].get("VesselRamp")
    pallet_RA   = float(line_dict["sequenceGeneral"].get("PalletStepRampAngle"))
    ramp        = model[ramp_name]    
    plet        = model["PLET_Frame"]
    
    stepNL_name     = f"00_LD_{ramp_angle}"
    stepClamp_name  = f"01_LD_{ramp_angle}"
    stepPallet_name = f"02_LD_{pallet_RA}"
    step01_name     = f"03_LD_{ramp_angle}"   # 10m WD
    
    stage           = "Stage_1"    # everything in here is Stage 1 
    
    # ------ 00 NL Step on Tensioner (Step 1) -------------------- #
    mylog.write(f"----- Step 00 ------ \n")
    mylog.write(f"...Creating NL Step (Pipe on Tensioner) for Ramp Angle {ramp_angle} \n")
    mylog.flush()
       
    ramp_cl         = model_cl[ramp_name]
    vessel_cl       = model_cl[vessel_name.split(" ")[-1]]
    line_cl         = model_cl["Pipe1"]
    clampAtSJ       = line_dict["sequenceGeneral"].get("Pipe_ClampSJ")
    lengthSJ_Clamp  = line_dict["sequenceGeneral"].get("LengthSJ_Clamp")
    
    # Get the SJ details to put back in later in the clamp step
    SJ_used = line_dict["SJGeneral"].get("SJrequired")
    if SJ_used and clampAtSJ:
        SJ_name  = line_cl.LineType[0]
        SJ_len   = line_cl.Length[0]
        TJ_name  = line_cl.LineType[1]
        TJ_len   = line_cl.Length[1]   
                       
        # swap it over for the NL step
        line_cl.LineType[0] = line_dict["pipeGeneral"].get("LineTypeName")
        line_cl.Length[0]   = SJ_len
        line_cl.LineType[1] = line_dict["pipeGeneral"].get("LineTypeName")
        line_cl.Length[1]   = TJ_len
        
    elif SJ_used and not clampAtSJ:
        
        line_cl.Length[0]   = float(line_dict["SJGeneral"].get("SJLen"))
        line_cl.LineType[0] = line_dict["pipeGeneral"].get("LineTypeName")
        line_cl.LineType[1] = line_dict["pipeGeneral"].get("LineTypeName")
        
        len_sec2 = line_cl.Length[2]
        len_sec3 = line_cl.Length[3] 
        len_sec4 = line_cl.Length[4]
        len_sec5 = line_cl.Length[5]
              
    else:
        len_sec0 = line_cl.Length[0]
        len_sec1 = line_cl.Length[1]
        len_sec2 = line_cl.Length[2]
        len_sec3 = line_cl.Length[3]
        len_sec4 = line_cl.Length[4]
        len_sec5 = line_cl.Length[5]
               
    # Adjust the Pipe Hangoff to the Tensioner   
    pipe_tens                  = line_dict["vesselGeneral"].get("PipeHangOff")    
    line_cl.EndAConnection     = line_dict["vesselGeneral"].get("VesselRamp")
    line_cl.EndAX              = vessel_json["Hang-off Locations"][pipe_tens][0]
    line_cl.EndAY              = vessel_json["Hang-off Locations"][pipe_tens][1]
    line_cl.EndAZ              = vessel_json["Hang-off Locations"][pipe_tens][2]
            
    # Destroy PLET frame
    model_cl.DestroyObject("PLET_Frame")
    model_cl.DestroyObject("PLET_Marker")
    model_cl.DestroyObject("PLET_WireAttach")
    
    try:
        model_cl.DestroyObject("ARYoke_1")
        model_cl.DestroyObject("ARYoke_2")
        model_cl.DestroyObject("ARYoke_3")
        model_cl.DestroyObject("ARYokeCOG")
        model_cl.DestroyObject("AR_Yoke_Hinge")
    except:
        pass
    
    # Destroy Unused Wires for this step
    try:
        model_cl.DestroyObject("Wire1")
        model_cl.DestroyObject("Wire2")
        model_cl.DestroyObject("Wire3")
    except:
        model_cl.DestroyObject("Wire1")
        model_cl.DestroyObject("Wire2")
    
    # Improve convergence conditions
    line_cl.FullStaticsMinDamping = 5
    line_cl.FullStaticsMaxDamping = 20 
    line_cl.Length[4] = line.Length[4]   
    line_cl.Length[5] = line.Length[5]            
    initLength_sq     = line_cl.Length[4]**2

    optim             = optimize.fsolve(_setZeroBM_pipeLen, initLength_sq, xtol = 1e-3, full_output = True)
    
    len_sec2 = line_cl.Length[2]   
    len_sec3 = line_cl.Length[3] 
    len_sec4 = line_cl.Length[4]   
    len_sec5 = line_cl.Length[5]
    
    static_status       = "NL RAMP ANGLE - PIPE ON TENSIONER"
    model_cl["General"].Comments = static_status     # Simple CLI: set before saving
    model_cl.SaveData('%s\%s_%s.dat' % (jobpath, stepNL_name, stage))

    filename      = '%s\%s_%s' % (jobpath, stepNL_name, stage)
    filename_dat  = filename + ".dat"
    wire_presence = False
    tempdict      = d_extractFunctions.extract_StaticRes(filename_dat, line_dict, "01", static_status, vessel_json, wire_presence)
    row.append(tempdict)
           
    # -------- 01 NL Clamped Step (Step 2) ----------------------------- #
    
    mylog.write(f"----- Step 01 ------ \n")
    mylog.write(f"...Creating NL Clamped Step for Ramp Angle {ramp_angle} \n")
    mylog.flush()
       
    vessel_name_cl  = line_dict["vesselGeneral"].get("VesselSelected").split(" ")[-1]
    vessel_cl       = model_cl[vessel_name.split(" ")[-1]]
    line_cl         = model_cl["Pipe1"]
    
    # Get total pipe length in the NL step before
    totalNLPipeLength = line_cl.CumulativeLength[-1]
    ActualSJLen       = float(line_dict["SJGeneral"].get("SJLen"))
    ActualTJLen       = float(line_dict["SJGeneral"].get("TJLen"))
             
    # Put back in the SJ if using and if clamping at SJ
    if SJ_used and clampAtSJ:
        line_cl.LineType[0] = SJ_name 
        line_cl.Length[0]   = float(lengthSJ_Clamp) 
        line_cl.LineType[1] = TJ_name 
        #
        line_cl.Length[2]   = len_sec2
        line_cl.Length[3]   = totalNLPipeLength - float(lengthSJ_Clamp) - ActualTJLen - len_sec2 - len_sec4 - len_sec5
        line_cl.Length[4]   = len_sec4 
        line_cl.Length[5]   = len_sec5
        
    elif SJ_used and not clampAtSJ:        
        line_cl.Length[0]   = ActualSJLen
        line_cl.Length[1]   = ActualTJLen
        line_cl.Length[3]   = totalNLPipeLength - len_sec4 - len_sec5 - ActualSJLen - ActualTJLen
        line_cl.Length[4]   = len_sec4 
        line_cl.Length[5]   = len_sec5
    else:
        line_cl.Length[0] = len_sec0 
        line_cl.Length[1] = len_sec1 
        line_cl.Length[2] = len_sec2 
        line_cl.Length[3] = len_sec3 
        line_cl.Length[4] = len_sec4 
        line_cl.Length[5] = len_sec5
            
    # Adjust the Clamp Hangoff Point here
    if vessel_name_cl == "Vega": 
        pipe_clamp = "HOM"
    elif vessel_name_cl == "Oceans" or vessel_name_cl == "Navica":
        pipe_clamp = "Clamp"    
      
    line_cl.EndAConnection     = line_dict["vesselGeneral"].get("VesselRamp")
    line_cl.EndAX              = vessel_json["Hang-off Locations"][pipe_clamp][0]
    line_cl.EndAY              = vessel_json["Hang-off Locations"][pipe_clamp][1]
    line_cl.EndAZ              = vessel_json["Hang-off Locations"][pipe_clamp][2]
    #line_cl.Length[3]          = abs(line_cl.EndAx)
    
    payout_cl = abs(vessel_json["Hang-off Locations"][pipe_tens][0] - vessel_json["Hang-off Locations"][pipe_clamp][0])
    ####line_cl.Length[3] += payout_cl   # Need to check this line against vega as well  
    initVesselX       = vessel_cl.InitialX
    optim             = optimize.fsolve(_setzeroBM_vesselX, initVesselX, xtol = 1e-3, full_output = True)
    
    len_sec3 = line_cl.Length[3] 
    
    static_status  = "NL RAMP ANGLE - PIPE CLAMPED"
    model_cl["General"].Comments = static_status     # Simple CLI: set before saving
    model_cl.SaveData('%s\%s_%s.dat' % (jobpath, stepClamp_name, stage))

    filename      = '%s\%s_%s' % (jobpath, stepClamp_name, stage)
    filename_dat  = filename + ".dat"
    wire_presence = False
    tempdict      = d_extractFunctions.extract_StaticRes(filename_dat, line_dict, "01", static_status, vessel_json, wire_presence)
    row.append(tempdict)
    
    ## ----------- 02 PLET on Pallet Step (Step 3) ------------------------ #
    mylog.write(f"----- Step 02 ------ \n")
    mylog.write(f"...Creating Pipe on Wire (Structure on Pallet) Step at Ramp Angle {pallet_RA} \n")
    mylog.flush()
    
    # Model Fudging to aid Convergence    
    model_pal = b_builderFunctions.fudge_staticParam(model_pal, [15, 30])        
    vesselPal = model_pal[vessel_name.split(" ")[-1]]
    
    # Delete Unused AR Wires (if not using Dual Mode)
    if line_dict["vesselGeneral"].get("AR_Mode") == "Single Mode":
        try:
            model_pal.DestroyObject("Wire2")
            model_pal.DestroyObject("Wire3")
        except:
            pass
        
    palletWireLen = float(line_dict["sequenceGeneral"].get("PalletStepWireLength"))
    wirePallet    = model_pal["Wire1"]
    wirePallet.NumberofSections       = 1
    wirePallet.Length[0]              = palletWireLen
    wirePallet.TargetSegmentLength[0] = 0.5
    
    pipePallet   = model_pal["Pipe1"]
    pletPallet   = model_pal["PLET_Frame"]
    rampPallet   = model_pal[ramp_name]
    rampAnglePal = abs(rampPallet.InitialRotation2)
    pipePallet.Length[3]  = len_sec3 #line_cl.Length[3]   
    
    # Add Pallet Relevant to the Vessel
    model_pal = b_builderFunctions.add_PalletObject(model_pal, line_dict)
    model_pal = b_builderFunctions.add_PLETContacts(model_pal, line_dict)
    
    # Move vessel to get optimal PIPE lift for this stage    
    initVesselX = vesselPal.InitialX
    
    # NEED CHANGE THIS PART!!!!!!!!!
    #optim = optimize.fsolve(c_sequenceFunctions.solve_PipeLiftPallet, initVesselX, xtol = 1e-3, full_output = True, args=(model_pal, vesselPal, rampAnglePal, pipePallet, pletPallet, vessel_json, mylog))
    
    filename      = '%s\%s_%s' % (jobpath, stepPallet_name, stage)
    model_pal     = c_sequenceFunctions.solve_pipeLift_pallet(
                                                        model               = model_pal,
                                                        payout              = 5.0,
                                                        firstGuessVesselX   = initVesselX,
                                                        line_dict           = line_dict,
                                                        solvingFile         = filename,
                                                        prev_vesselX        = initVesselX,
                                                        #conv_flag           = 1,
                                                        mylog               = mylog
                                                    )
    
    static_status                   = "PIPE ON WIRE STEP - PLET ON PALLET"
    model_pal["General"].Comments   = static_status     # Simple CLI: set before saving
    model_pal.SaveData('%s\%s_%s.dat' % (jobpath, stepPallet_name, stage))
    #filename       = '%s\%s_%s' % (jobpath, stepPallet_name, stage)
    filename_dat   = filename + ".dat"
    wire_presence  = True
    tempdict       = d_extractFunctions.extract_StaticRes(filename_dat, line_dict, "01", static_status, vessel_json, wire_presence)
    row.append(tempdict)
        
    mylog.write(f"Created pallet basemodel \n")
    mylog.flush()
              
    ## -------- 03++ Begin Steps with PLET Underwater (Step 4 onwards) --------- #     
    ramp_angle = pallet_RA
    mylog.write(f"----- Step 03 ------ \n")
    mylog.write(f"...Creating Initial Step (PLET Submerged 10m) for Ramp Angle {ramp_angle} \n")
    mylog.flush()
               
    # Model Fudging to aid Convergence    
    model  = b_builderFunctions.fudge_staticParam(model, [5, 20])   
    vessel = model[vessel_name.split(" ")[-1]]
    
    # Delete Unused AR Wires (if not using Dual Mode)
    if line_dict["vesselGeneral"].get("AR_Mode") == "Single Mode":
        try:
            model.DestroyObject("Wire2")
            model.DestroyObject("Wire3")
        except:
            pass
                                  
    line.Length[3]  = len_sec3 #line_cl.Length[3]   
    initVesselX     = vesselPal.InitialX ###vessel_cl.InitialX 
    mock_payout      = 50  
    plet.DegreesOfFreedomInStatics = "X,Y,Z"
    jackdown         = False
    solving_file     = '%s\%s_%s.dat' % (jobpath, step01_name, stage)
    conv_flag        = 1
    first_step       = True
        
    model, conv_flag = c_sequenceFunctions.solve_WireLift(model, mock_payout, initVesselX, line_dict, solving_file, initVesselX, conv_flag, jackdown, mylog, first_step)

    # Use Calculated Positions
    model.CalculateStatics()
    model.UseCalculatedPositions(SetLinesToUserSpecifiedStartingShape=False)
    # Free the PLET rotations
    plet.DegreesOfFreedomInStatics = "All"
    plet.InitialRotation1 = 0
    plet.InitialRotation2 = -1*rampAnglePal
    plet.InitialRotation3 = 0
    # Solve again the Wire Lift with Freed Rotation
    model.CalculateStatics() 
               
    # -------------- STEP 03 - PLET just submerged -------------------- #
    static_status  = "NL RAMP ANGLE - WIRE"
    model["General"].Comments = static_status
    model.SaveData('%s\%s_%s.dat' % (jobpath, step01_name, stage))
    filename       = '%s\%s_%s' % (jobpath, step01_name, stage)
    #
    
    # - Check Feasibility of Proposed First Ramp Angle - #
    filename_dat  = filename + ".dat"
    wire_presence = True
    tempdict = d_extractFunctions.extract_StaticRes(filename_dat, line_dict, "01", static_status, vessel_json, wire_presence)
    
    # ---- Easy hardcode condition for beginning of simulation ---- #        
    while float(tempdict["Pipe Max LCC"]) > 0.8:
            
            customRA              = line_dict["vesselGeneral"].get("CustomRampAngle")
            old_rampAngle         = -1*ramp.InitialRotation2
            new_rampAngle         = c_sequenceFunctions.change_RampAngle(tempdict, line_dict, customRA)[0]
            # Simple CLI: stop when no lower ramp angle is available (the loop had no exit)
            if float(new_rampAngle) >= float(old_rampAngle):
                mylog.write(f"No lower ramp angle available below {old_rampAngle}. Keeping it (Pipe Max LCC {tempdict['Pipe Max LCC']}). \n")
                print(f"WARNING: no lower ramp angle available below {old_rampAngle}; continuing with LCC above 0.8.")
                break
            ramp.InitialRotation2 = -1*new_rampAngle
            ramp_angle            = -1*ramp.InitialRotation2
            print(f"Jacking down to {ramp_angle}. NL ramp angle too steep.")
            mylog.write(f"Jacking down to {ramp_angle}. NL ramp angle too steep. \n")
            #
            initVesselX     = vessel.InitialX
            jackdown_payout = 0  
            first_step      = False
            model, conv_flag = c_sequenceFunctions.solve_WireLift(model, jackdown_payout, initVesselX, line_dict, solving_file, initVesselX, conv_flag, jackdown, mylog, first_step)             
            #
            static_status = f"NL RAMP ANGLE TOO STEEP. JACKED DOWN FROM {old_rampAngle}."
            step01_name   = f"03_LD_{ramp_angle}"
            model["General"].Comments = static_status
            model.SaveData('%s\%s_%s.dat' % (jobpath, step01_name, stage))
            filename       = '%s\%s_%s' % (jobpath, step01_name, stage)
            filename_dat   = filename + ".dat"
            wire_presence  = True
            tempdict       = d_extractFunctions.extract_StaticRes(filename_dat, line_dict, "01", static_status, vessel_json, wire_presence) 
            
    row.append(tempdict)
    mylog.write("Saving Step03 - PLET at 10m WD \n")
    mylog.flush()
    model.SaveData('%s\%s_%s.dat' % (jobpath, step01_name, stage))
    filename       = '%s\%s_%s' % (jobpath, step01_name, stage)
    
    # ------ STEP 03 + n: Individual static steps per Buoy ----------------- #
    b_builderFunctions.create_BuoyConnection(model, line_dict, stage)
    model.SaveData('%s\%s_%s-BuoyYoke.dat' % (jobpath, step01_name, stage))    
    basemodel = '%s\%s_%s-BuoyYoke.dat' % (jobpath, step01_name, stage)
    row = c_sequenceFunctions.deploy_buoy(jobpath,
                                     vessel_json,
                                     basemodel,
                                     ramp_angle,
                                     vessel_name,
                                     wireline1, 
                                     line_dict,
                                     row,
                                     mylog      
                                    )
    
    if baseOnly == "NO":
            
            # ------ STEP i: Create auto sequence based on payout rate -------- #
            buoyNo          = int(line_dict["buoyGeneral"].get("BuoyancyModuleQuantity"))
            last_buoy_step  = f"0{buoyNo+3}_LD_{ramp_angle}"        
            basemodel       = '%s\%s_%s.dat' % (jobpath, last_buoy_step, stage)
            row = c_sequenceFunctions.payout_wire_until_land(   jobpath,
                                                            vessel_json,
                                                            basemodel,                           
                                                            ramp_angle,
                                                            vessel_name,
                                                            line_dict,
                                                            plet_dict,
                                                            mudmat_dict,
                                                            row,
                                                            mylog
                                                        )
    
    # -------------- Export results to pandas and excel --------------- #
    df1                         = pd.DataFrame(row)
    df1["Wire1 Length [m]"]     = df1["Wire1 Length [m]"].replace("N/A", 0)
    df1["Wire1 Length [m]"]     = pd.to_numeric(df1["Wire1 Length [m]"] )
    
    df1["Wire Payout [m]"]      = df1["Wire1 Length [m]"].diff().round(1)
    df1["Vessel Movement [m]"]  = df1["Vessel X [m]"].diff().round(1)
    print(df1)
    excel_file_save = jobID.rsplit(".", 1)[0] + "_StaticResults.xlsx"
    mylog.write("Saving static results to Excel File: %s \n" % excel_file_save)
    df1.to_excel("%s\%s" % (jobpath, excel_file_save), sheet_name = "StaticResults")
    
    # ------ Format Laytable ----- #
    # Simple CLI: the template is optional (it only exists as a Google Sheet in the original tool)
    laytable_base = constants.LAYTABLE_TEMPLATE
    laytableSave  = jobID.rsplit(".", 1)[0] + "_Laytable.xlsx"
    savePath = "%s\%s" % (jobpath, laytableSave)
    if os.path.exists(laytable_base):
        d_extractFunctions.format_laytable(
            laytable_base,
            savePath,
            df1,
            line_dict
        )
        mylog.write("Saving static results to Laytable: %s \n" % laytableSave)
    else:
        mylog.write("Laytable template %s not found - formatted laytable skipped (see StaticResults.xlsx). \n" % laytable_base)
        print(f"NOTE: lay table template not found ({laytable_base}); only {excel_file_save} was written.")
                        
def create_basemodels(
    jobpath             : str,
    myJSONfile          : str,
    vessel_name         : str,        
    vessel_file_path    : str,
    vessel_base         : str,
    line_dict           : dict,
    baseOnly            : str,
    currentSpeed        : float,
    currentDir          : float,
    mylog               : any
    ):  
    
    def _consolidate_model(model, pipe, wire, wire2, wire3, stage, plet_modelling, currentSpeed, currentDir):
        
        '''
        Function    :   Put together a set of functions that create the structure, the pipe, mesh the pipe, the AR, the AR yoke if present, move the PLET to correct starting pos,
                        set the current speed and direction, the pipe catenary.
                        
                        Takes in an existing model, pipe, and 3 wires, and modifies them.
                        
        Returns     :   PLET dict, mudmat dict

        '''
        #
        plet_dict, mudmat_dict = b_builderFunctions.create_2ndEndStructure(model, line_dict, plet_modelling, stage)          
        b_builderFunctions.create_linetype(model, pipe, line_dict) 
        b_builderFunctions.create_lineSimpleMesh(pipe)
        b_builderFunctions.create_ARLinetype(model, wire, wire2, wire3, line_dict, vessel_json) 
        b_builderFunctions.create_ARConnection(model, wire, wire3, line_dict, stage)
        move_PLET_10m(model, line_dict) 
        #
        b_builderFunctions.create_NLModel(
            model,
            pipe,
            line_dict,
            vessel_name,
            w_depth,
            stage,
            currentSpeed,
            currentDir
        )
        
        return model, plet_dict, mudmat_dict
                    
    with open (myJSONfile) as json_file:
        line_dict = json.load(json_file)
        
    w_depth = float(line_dict["sequenceGeneral"].get("WD_Max"))
    
    if baseOnly == "NO":
        mylog.write(f"Laydown Sequence Build Begun for WD: {w_depth}m. ")
    else:
        mylog.write("Preparing Basefile(s) for Checking.")
    mylog.flush()
       
    # ------------------- Load vessel JSON ------------- #
    vessel_loc  = os.path.join(constants.VESSEL_DB_DIR, vessel_name, f"{vessel_name}_coords.json")

    with open (vessel_loc) as json_file:
        vessel_json = json.load(json_file)

    pipeID  = constants.PIPE_NAME
    wireID1 = constants.ANR_WIRE_1
    wireID2 = constants.ANR_WIRE_2
    wireID3 = constants.ANR_WIRE_3
    
    plet_modelling = line_dict["structureGeneral"].get("PLETModellingOpt") 
    
    # Create 3 AR wires, and then later delete them if not necessary
        
    # Spare Model with the 2nd Stage PLET
    if plet_modelling == "Frame & Mudmat (With Wings)":
        model_2   = of.Model(os.path.join(vessel_file_path, vessel_name, vessel_base))
        pipe_2    = model_2.CreateObject(of.otLine, pipeID)
        wire_2a   = model_2.CreateObject(of.otLine, wireID1)
        wire_2b   = model_2.CreateObject(of.otLine, wireID2)
        wire_2c   = model_2.CreateObject(of.otLine, wireID3)
        model_2["General"].BuoysIncludedInStatics = "Individually specified"
        model_2["General"].Comments = "Base model for when the frame and mudmat are modelled separately due to the wings being opened."
        #
        model_2, plet_dict, mudmat_dict = _consolidate_model(model_2, pipe_2, wire_2a, wire_2b, wire_2c, "Stage_2", plet_modelling, currentSpeed, currentDir)
        b_builderFunctions.create_BuoyConnection(model_2, line_dict, stage="Stage_2")
        model_2.SaveData("%s/Stage_2_PLET.dat" % jobpath)
    else:
        model_2 = of.Model()
        
    # Model Creation - BASE
    model_1   = of.Model(os.path.join(vessel_file_path, vessel_name, vessel_base))
    model_1["General"].BuoysIncludedInStatics = "Individually specified"
    pipe_1    = model_1.CreateObject(of.otLine, pipeID)
    wire_1a   = model_1.CreateObject(of.otLine, wireID1)
    wire_1b   = model_1.CreateObject(of.otLine, wireID2)
    wire_1c   = model_1.CreateObject(of.otLine, wireID3)
    model_1, plet_dict, mudmat_dict = _consolidate_model(model_1, pipe_1, wire_1a, wire_1b, wire_1c, "Stage_1", plet_modelling, currentSpeed, currentDir)
    
    model_1.SaveData("%s/Stage_1_PLET.dat" % jobpath)
    
    # Model Creation - NL and Clamped Steps
    model_cl  = of.Model("%s/Stage_1_PLET.dat" % jobpath)
    model_cl["General"].BuoysIncludedInStatics = "Individually specified"
    
    # Model Creation - Pallet Step
    model_pal = of.Model("%s/Stage_1_PLET.dat" % jobpath)
    model_pal["General"].BuoysIncludedInStatics = "Individually specified"
    
    # Do the Steps 00, 01, 02, 03 here, and call the buoy steps and then the following steps        
    create_static_sequence(     jobpath, vessel_name, vessel_json, 
                                model_1, model_cl, model_pal,
                                pipe_1, wire_1a, 
                                line_dict, plet_dict, mudmat_dict, 
                                baseOnly, mylog
                                )
                               
def main_LD(
    myJSONfile  : str, 
    jobDir      : str, 
    baseOnly    : str
    ):
             
    with open (myJSONfile) as json_file:
        line_dict = json.load(json_file)
        
    # ----- Get Vessel Data to load Vessel Dict ----- #
    vessel_database_folder = constants.VESSEL_DB_DIR
    vessel_selected        = line_dict["vesselGeneral"].get("VesselSelected")

    if vessel_selected == "Seven Vega":
        vessel_shortname     = 'vega'
        vessel_base          = "_vegaBase_3.2.dat"

    elif vessel_selected == "Seven Navica":
        vessel_shortname     = 'navica'
        vessel_base          = "_navicaBase.dat"

    elif vessel_selected == "Seven Oceans":
        vessel_shortname     = 'oceans'
        vessel_base          = "_oceansBase.dat"

    else:
        raise ValueError(f"Unknown vesselGeneral.VesselSelected '{vessel_selected}' "
                         "(use Seven Vega, Seven Oceans or Seven Navica)")

    jobLocDir   = jobDir

    currentOption = line_dict["General"].get("CurrentOption")

    if currentOption == "No Current":
        currentSpeed  = 0.0
        currentDir    = 0.0
        curPathName   = "noCurrent"

    elif currentOption == "Current In Lay Dir. (0deg)":
        currentSpeed    = 1.0
        currentDir      = 0.0
        curPathName     = "InLineCurrent"

    elif currentOption == "Current Against Lay Dir. (180deg)":
        currentSpeed    = 1.0
        currentDir      = 180.0
        curPathName     = "AgainstCurrent"

    else:
        raise ValueError(f"Unknown General.CurrentOption '{currentOption}'")

    curPath   = os.path.join(jobLocDir, curPathName)
    newJobDir = curPath

    print("*Main Job JSON File: %s" % myJSONfile)
    print("*Job Location Folder: %s" % newJobDir)

    # Simple CLI: log name built with os.path (the old rsplit("/") broke on Windows paths)
    logName   = os.path.basename(myJSONfile)
    logdir    = os.path.join(newJobDir, curPathName + logName.replace(".json", ".log"))
    os.makedirs(curPath, exist_ok=True)
    
    print(f"*Check the job logfile here: {logdir}")
    
    # Create Manual Log File
    with open(logdir, 'w') as mylog:
        mylog.write("---------------------------------------------\n")
        mylog.write("Path to Job JSON File: %s\n" % myJSONfile)
        mylog.write("Job Location SubFolder: %s\n" % newJobDir)
        mylog.write("Current Speed: %s | Current Direction: %s\n" % (currentSpeed, currentDir))
        mylog.write("Starting......\n")
        mylog.write(f"Start Time: {time.ctime(time.time())} \n")
        mylog.flush()
    
        create_basemodels(
            newJobDir,    
            myJSONfile,
            vessel_shortname,
            vessel_database_folder,
            vessel_base,
            line_dict,
            baseOnly,
            currentSpeed,
            currentDir,
            mylog   
        )
    
        mylog.write(f"End Time: {time.ctime(time.time())} \n")
        mylog.flush()

    return newJobDir


   