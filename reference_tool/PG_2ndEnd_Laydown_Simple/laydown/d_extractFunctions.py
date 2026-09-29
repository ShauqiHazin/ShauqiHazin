import os, sys
import json
from glob import glob
import OrcFxAPI as of
import numpy as np
import pandas as pd
import shutil
from openpyxl import load_workbook
from openpyxl.styles import NamedStyle, Font, Border, Side, Alignment, PatternFill, numbers

from . import constants

'''
Script      :   c_extractResults.py

Function    :   Contains functions to extract results from Orcaflex .sim files during runtime, 
                to rerun the result extraction in case of any manual interventions, and to produce a laytable 
                in the required PG format.
                
Dependents  :   * a_buildSequence.py
                * b_sequenceFunctions.py
                * UI_func.py
                
Last update :   22 April 2026
Author      :   S.O
'''
   
def format_laytable(
    sourcepath  : str,
    destipath   : str,
    df_raw      : any,
    line_dict   : dict
):
    
    try:
        shutil.copyfile(sourcepath, destipath)
        print(f"Workbook copied successfully from '{sourcepath}' to '{destipath}'")
    except FileNotFoundError:
        print(f"Error: Source file '{sourcepath}' not found.")
    except Exception as e:
        print(f"An error occurred during copying: {e}")

    wb = load_workbook(destipath)
    ws = wb["LaydownLaytable"]

    # ---- Some Calcs for the Laytable ----- #

    df_raw["CumSumPayout"] = df_raw["Wire Payout [m]"].cumsum()
    # For cases withOUT wire at all
    try:
        df_raw["WireHorizLen"]      = abs(df_raw["Wire1 EndA X [m]"] - df_raw["Wire1 EndB X [m]"])
        df_raw["WireVertLen"]       = abs(df_raw["Wire1 Hangoff [m]"] - df_raw["Wire1 EndB Z [m]"])
        df_raw["TotalCatLen"]       = df_raw["Wire1 Length [m]"] + df_raw["Pipe Suspended Arc Len [m]"]
    except:
        df_raw["WireHorizLen"]      = 0.0
        df_raw["WireVertLen"]       = 0.0
        df_raw["TotalCatLen"]       = df_raw["Pipe Suspended Arc Len [m]"]
        
    # --- For cases with 2 wires  
    try:
        df_raw["Max Wire Lift"]     = max(df_raw["Wire1 Lift [deg]"], df_raw["Wire2 Lift [deg]"])
        df_raw["Wire Angle [deg]"]  = df_raw["Vessel Ramp Angle [deg]"] - df_raw["Max Wire Lift"]
    except:
        try:
            df_raw["Wire Angle [deg]"]  = df_raw["Vessel Ramp Angle [deg]"] - df_raw["Wire1 Lift [deg]"]
        except:
            # for step without wire at all
            df_raw["Wire Angle [deg]"] = 0.0
    #
    
    df_raw["PipeHorizLen"] = abs(df_raw["Pipe EndA X [m]"] - df_raw["Pipe TDP X [m]"])
    df_raw["PipeVertLen"]  = abs(df_raw["Pipe EndA Z [m]"] - df_raw["Pipe TDP Z [m]"])
    #
    df_raw["RampAngleRadians"] = df_raw["Vessel Ramp Angle [deg]"]*0.0174533       
    df_raw["WireAngleRadians"] = df_raw["Wire Angle [deg]"]*0.0174533
    try:
        df_raw["TotalWireTopTension"] = df_raw["Wire1 Top Tension [mT]"] + df_raw["Wire2 Top Tension [mT]"]    
    except:
        try:
            df_raw["TotalWireTopTension"] = df_raw["Wire1 Top Tension [mT]"]
        except:
            df_raw["TotalWireTopTension"] = 0.0

    df_raw["TotalWireTopTension"]   = df_raw["TotalWireTopTension"].replace('N/A', 0)
    df_raw["WireAngleRadians"]      = df_raw["WireAngleRadians"].replace('N/A', 0)
    
    df_raw["TotalWireHorizTopTension"] = df_raw["TotalWireTopTension"].astype(float)*np.cos(df_raw["WireAngleRadians"].astype(float))

    ws.cell(row=1, column=2).value = line_dict["vesselGeneral"].get("VesselSelected")
    ws.cell(row=2, column=2).value = line_dict["General"].get("scopeID")
    ws.cell(row=3, column=2).value = "2nd End Laydown"
    ws.cell(row=4, column=2).value = line_dict["pipeGeneral"].get("Content")
    ws.cell(row=5, column=2).value = line_dict["vesselGeneral"].get("AR_Mode") 
    ws.cell(row=6, column=2).value = line_dict["General"].get("WD")

    for index, row in df_raw.iterrows():
        writerow = 13 + index
        ws.cell(row=writerow, column=1).value = row["Step"]
        ws.cell(row=writerow, column=2).value = row["Wire Payout [m]"]
        ws.cell(row=writerow, column=3).value = row["CumSumPayout"]         # Total Paid Out
        ws.cell(row=writerow, column=4).value = row["WireHorizLen"]         # Horiz Proj Len Wire (calc)
        ws.cell(row=writerow, column=5).value = row["WireVertLen"]          # Vert Proj Len Wire (calc)
        #
        ws.cell(row=writerow, column=6).value = row["Vessel Movement [m]"]    # Vessel Move
        ws.cell(row=writerow, column=7).value = row["Vessel X [m]"]           # Vessel Pos
        #
        ws.cell(row=writerow, column=8).value = row["Layback [m]"]              # Layback
        ws.cell(row=writerow, column=9).value = row["TotalCatLen"]          # Total Cat Len (calc)
        #
        ws.cell(row=writerow, column=10).value = row["PLET Clearance [m]"]      # plet clearance
        ws.cell(row=writerow, column=11).value = row["PLET Z [m]"]              # plet depth
        ws.cell(row=writerow, column=12).value = row["PLET Tilt [deg]"]         # plet angle
        #
        ws.cell(row=writerow, column=13).value = row["TotalWireTopTension"]         # wire top tension (include second wire too if avail.)
        ws.cell(row=writerow, column=14).value = row["TotalWireHorizTopTension"]    # horiz top tension (calc resolve)
        ws.cell(row=writerow, column=15).value = row["Bollard Pull [mT]"]           # bottom tension 
        #
        ws.cell(row=writerow, column=16).value = row["Pipe Suspended Arc Len [m]"]      # pipe suspend len 
        ws.cell(row=writerow, column=17).value = row["PipeHorizLen"]                    # pipe horiz len (calc)
        ws.cell(row=writerow, column=18).value = row["PipeVertLen"]                     # pipe vert len (calc)
        #
        ws.cell(row=writerow, column=19).value = row["Vessel Ramp Angle [deg]"]         # ramp angle
        ws.cell(row=writerow, column=20).value = row["Wire Angle [deg]"]                # wire angle, get max between 2 wires if necess.
        ws.cell(row=writerow, column=21).value = row["Pipe Max Stress [MPa]"]           # max stress
        #
        ws.cell(row=writerow, column=22).value = row["Status"]    # comments

    style_dec_zero = NamedStyle(name = "decimal_0")
    style_dec_zero.number_format = '0'
    style_dec_one  = NamedStyle(name = "decimal_1") 
    style_dec_one.number_format = '0.0'
    center_alignment = Alignment(horizontal='center', vertical='center')

    for index, row in df_raw.iterrows():
        writerow = 13 + index
        for col in range(1,22):
            if col in [12, 19, 20]:
                ws.cell(row=writerow, column=col).style = style_dec_one
            else:
                ws.cell(row=writerow, column=col).style = style_dec_zero
            ws.cell(row=writerow, column=col).alignment = center_alignment
    
    wb.save(destipath)
    wb.close()

    df_open = pd.read_excel(destipath, sheet_name = "LaydownLaytable", header = 12)

    print(df_open)

def extract_StaticRes(
    filename            : str,
    line_dict           : dict, 
    ID                  : str, 
    static_status       : str, 
    vessel_json         : json, 
    wire_presence=None):
       
    print("Extracting results for file: %s" % filename)
    #    
    if static_status == "Extraction has been rerun.":
        stepstring = filename.split("_")[0]
        print(f"stepstring: {stepstring}")
        Step = int(filename.split("_")[0])
    else:        
        filename_sansdir  = filename.split("\\")[-1]
        partition_sansdir = filename_sansdir.split("_")[0]               
        Step = int(filename_sansdir.partition("_")[0])
    
    print(f"Step: {Step}")
    
    extractModel = of.Model(filename)

    extractModel.CalculateStatics()
        
    if line_dict["vesselGeneral"].get("AR_Mode") == "Dual Mode (A&R Beam)":
        ar_beam_bool = True
    else:
        ar_beam_bool = False
    
    # Find ramp in model
    vessel_name = line_dict["vesselGeneral"].get("VesselSelected").split(" ")[-1]
    ramp_name   = line_dict["vesselGeneral"].get("VesselRamp")
    ramp        = extractModel[ramp_name]
    vessel      = extractModel[vessel_name.capitalize()]
    vesseltype  = vessel.VesselType    
    env         = extractModel["Environment"]
    line        = extractModel["Pipe1"]
    if wire_presence:
        wireline    = extractModel["Wire1"]
        plet        = extractModel["PLET_Frame"]
        plet_ref    = extractModel["PLET_Marker"]
    
        if ar_beam_bool:
            ar_beam   = extractModel["A&R spreader beam"]
            wireline2 = extractModel["Wire2"]
    #    
    rg = line.RangeGraph(
        "Curvature",
        of.pnStaticState,
        None,
        of.arSpecifiedSections(1, -1),
    )
    d = dict(zip(rg.X, rg.Mean))
    arc_maxCurv  = max(d, key = d.get)
    upperSbend   = arc_maxCurv * (1 - 1 / 6)
    lowerSbend   = arc_maxCurv * (1 + 1 / 4)
    sagbendRange = of.arSpecifiedArclengths(upperSbend, lowerSbend)
    
    subdict = {}
    
    pipe_line_type = extractModel["Pipe1"].LineType[-1]
    # Pipe
    subdict["ID"]   = ID
    subdict["Step"] = Step #static_stepcount
    subdict["Filename"] = filename
    subdict["Pipe OD [mm]"]  = 1e3*extractModel[pipe_line_type].OD    #only the main pipe, not the SJ
    subdict["Pipe WT [mm]"]  = 1e3*(extractModel[pipe_line_type].OD - extractModel[pipe_line_type].ID)/2
    subdict["Pipe Contents"] = line_dict["pipeGeneral"].get("Content")
    # Vessel
    subdict["Vessel Ramp Angle [deg]"]  = -1*ramp.InitialRotation2
    subdict["Vessel X [m]"]             = round(vessel.InitialX)
    subdict["Vessel Y [m]"]             = vessel.InitialY
    subdict["Vessel Z [m]"]             = vessel.InitialZ
    # Env
    subdict["WD [m]"]           = env.WaterDepth
    subdict["Cur. Speed [m/s]"] = env.RefCurrentSpeed
    subdict["Cur. Dir [deg]"]   = env.RefCurrentDirection
    # Pipeline Loc
    subdict["Pipe EndA X [m]"] = line.StaticResult("X", of.oeEndA)
    subdict["Pipe EndA Y [m]"] = line.StaticResult("Y", of.oeEndA)
    subdict["Pipe EndA Z [m]"] = line.StaticResult("Z", of.oeEndA)
    subdict["Pipe TDP X [m]"]  = line.StaticResult("X", of.oeTouchdown)
    subdict["Pipe TDP Y [m]"]  = line.StaticResult("Y", of.oeTouchdown)
    subdict["Pipe TDP Z [m]"]  = line.StaticResult("Z", of.oeTouchdown)
    subdict["Pipe EndB X [m]"] = line.StaticResult("X", of.oeEndB)
    subdict["Pipe EndB Y [m]"] = line.StaticResult("Y", of.oeEndB)
    subdict["Pipe EndB Z [m]"] = line.StaticResult("Z", of.oeEndB)
    subdict["Pipe Suspended Arc Len [m]"] = line.StaticResult("Arc Length", of.oeTouchdown)  #check
    # Pipe Tensions
    subdict["Pipe EndA Tension [mT]"] = line.StaticResult("Effective Tension", of.oeEndA)/constants.GRAVITY
    subdict["Pipe TDP Tension [mT]"]  = line.StaticResult("Effective Tension", of.oeTouchdown)/constants.GRAVITY
    subdict["Pipe EndB Tension [mT]"] = line.StaticResult("Effective Tension", of.oeEndB)/constants.GRAVITY
    # Pipe BM
    subdict["Pipe EndA BM [kNm]"] = line.StaticResult("Bend Moment", of.oeEndA)
    subdict["Pipe TDP BM [kNm]"]  = line.StaticResult("Bend Moment", of.oeTouchdown)
    subdict["Pipe EndB BM [kNm]"] = line.StaticResult("Bend Moment", of.oeEndB)
    subdict["Pipe Max BM [kNm]"]  = max(
            line.RangeGraph("Bend Moment", of.pnStaticState).Mean
        )
    # Pipe Stress
    subdict["Pipe Max Stress [MPa]"] = max(
            line.RangeGraph("Max Von Mises Stress", of.pnStaticState).Mean
        )*0.001
    
    # Pipe Strain
    maxstrain = max(
            line.RangeGraph("Worst ZZ Strain", of.pnStaticState).Mean
        , key = abs)
    subdict["Pipe Max Strain [%]"] = maxstrain
    
    # Pipe LCC - condition A
    extractModel["Code Checks"].DNVOSF101GammaF = 1.2
    extractModel["Code Checks"].DNVOSF101GammaE = 0.7
    extractModel["Code Checks"].DNVOSF101GammaC = 1.0
    subdict["Pipe EndA LCC"] = line.StaticResult("DNV ST F101 Load Controlled", of.oeEndA)
    subdict["Pipe TDP LCC"]  = line.StaticResult("DNV ST F101 Load Controlled", of.oeTouchdown)
    subdict["Pipe EndB LCC"] = line.StaticResult("DNV ST F101 Load Controlled", of.oeEndB)
    subdict["Pipe Max LCC"]  = max(
            line.RangeGraph("DNV ST F101 Load Controlled", of.pnStaticState).Mean
        )
    
     # Wire
    if wire_presence:
        # PLET Loc
        subdict["PLET X [m]"] = plet_ref.StaticResult("X")
        subdict["PLET Y [m]"] = plet_ref.StaticResult("Y")
        subdict["PLET Z [m]"] = plet_ref.StaticResult("Z")
        subdict["PLET Tilt [deg]"]    = plet_ref.StaticResult("Rotation 2")
        subdict["PLET Clearance [m]"] = subdict["WD [m]"] + subdict["PLET Z [m]"]
   
        subdict["Wire1 Top Tension [mT]"]  = wireline.StaticResult("Effective Tension", of.oeEndA)/constants.GRAVITY
        subdict["Wire1 PLET Tension [mT]"] = wireline.StaticResult("Effective Tension", of.oeEndB)/constants.GRAVITY
        subdict["Wire1 Length [m]"]        = wireline.StaticResult("Arc length", of.oeEndB)
        subdict["Wire1 EndA X [m]"]        = wireline.StaticResult("X", of.oeEndA)
        subdict["Wire1 Hangoff [m]"]       = wireline.StaticResult("Z", of.oeEndA)
        subdict["Wire1 EndB X [m]"]        = wireline.StaticResult("X", of.oeEndB)
        subdict["Wire1 EndB Z [m]"]        = wireline.StaticResult("Z", of.oeEndB)
        wire1Angle                         = wireline.StaticResult("Node declination", objectExtra = of.oeEndA) - 90
        subdict["Wire1 Lift [deg]"]        = -1*ramp.InitialRotation2 - wire1Angle
        #
        if ar_beam_bool:
            subdict["Wire2 Top Tension [mT]"]  = wireline2.StaticResult("Effective Tension", of.oeEndA)/constants.GRAVITY
            subdict["Wire2 PLET Tension [mT]"] = wireline2.StaticResult("Effective Tension", of.oeEndB)/constants.GRAVITY
            subdict["Wire2 Length [m]"]        = wireline2.StaticResult("Arc length", of.oeEndB)
            subdict["Wire2 Hangoff [m]"]       = wireline2.StaticResult("Z", of.oeEndA)
            wire2Angle                         = wireline2.StaticResult("Node declination", objectExtra = of.oeEndA) - 90
            subdict["Wire2 Lift [deg]"]        = -1*ramp.InitialRotation2 - wire2Angle    
            subdict["Bollard Pull [mT]"]       = subdict["Wire1 Top Tension [mT]"] * np.cos(np.radians(wire1Angle)) + subdict["Wire2 Top Tension [mT]"] * np.cos(np.radians(wire2Angle))
        #
        if ar_beam_bool == False:
            subdict["Bollard Pull [mT]"]      = subdict["Wire1 Top Tension [mT]"] * np.cos(np.radians(wire1Angle))
            
        subdict["Pipe Angle [deg]"]       = 'N/A'
        subdict["Pipe Lift [deg]"]        = 'N/A'
            
    else:
        
        subdict["PLET X [m]"]         = 'N/A'
        subdict["PLET Y [m]"]         = 'N/A'
        subdict["PLET Z [m]"]         = 'N/A'
        subdict["PLET Tilt [deg]"]    = 'N/A'
        subdict["PLET Clearance [m]"] = 'N/A'
        
        subdict["Wire1 Top Tension [mT]"]  = 'N/A'
        subdict["Wire1 PLET Tension [mT]"] = 'N/A'
        subdict["Wire1 Length [m]"]        = 'N/A'
        subdict["Wire1 EndA X [m]"]        = 'N/A'
        subdict["Wire1 Hangoff [m]"]       = 'N/A'
        subdict["Wire1 EndB X [m]"]        = 'N/A'
        subdict["Wire1 EndB Z [m]"]        = 'N/A'
        subdict["Wire1 Lift [deg]"]        = 'N/A'
        
        pipeAngle = line.StaticResult("Node declination", objectExtra = of.oeEndA) - 90
        subdict["Pipe Angle [deg]"]       = pipeAngle  
        subdict["Pipe Lift [deg]"]        = -1*ramp.InitialRotation2 - pipeAngle
        subdict["Bollard Pull [mT]"]      = subdict["Pipe EndA Tension [mT]"] * np.cos(np.radians(pipeAngle))
    
    if wire_presence:        
        # Wire Length on Seabed    
        seabedClearance = wireline.RangeGraph(
                        "Seabed Clearance",
                        of.pnStaticState,
                        None,
                        of.arSpecifiedSections(1, -1),
                    ) 

        X = np.array(seabedClearance.X)
        Y = np.array(seabedClearance.Mean)

        try:
            loc_contact    = X[np.where(Y <= 0)]
            length_contact = loc_contact[-1] - loc_contact[0]
        except:
            length_contact = 0.0

        subdict["Wire Length on Seabed [m]"] = length_contact
    
        if ar_beam_bool:
            subdict["Beam X [m]"] = ar_beam.StaticResult("X")
            subdict["Beam Y [m]"] = ar_beam.StaticResult("Y")
            subdict["Beam Z [m]"] = ar_beam.StaticResult("Z")
            subdict["Beam Rotation [deg]"] = ar_beam.StaticResult("Rotation 2")
        
    else:
        subdict["Wire Length on Seabed [m]"] = 'N/A'
    
    # Layback
    subdict["Layback [m]"]         = ramp.StaticResult("X") - subdict["Pipe TDP X [m]"]
    
    # Step Indicator
    subdict["Status"] = static_status
    
    # Limit Warnings
    # Simple CLI: fall back to the old GUI vessel capacities when the vessel JSON lacks the keys
    vessel_short    = vessel_json.get("Name", "")
    AR_Lim          = (vessel_json.get("AR Winch Limit") or {}).get(line_dict["vesselGeneral"].get("AR_Mode")) \
                      or constants.AR_WINCH_LIMITS.get(vessel_short, float("inf"))
    BollardPullLim  = (vessel_json.get("Bollard Pull Limit") or {}).get("Bollard Pull") \
                      or constants.BOLLARD_PULL_LIMITS.get(vessel_short, float("inf"))
    
    lim_warnings = "-"
    
    total_wire_tens = 0
    if wire_presence:
        wire1_tens = float(subdict["Wire1 Top Tension [mT]"])
        if ar_beam_bool:
            wire1_tens = float(subdict["Wire1 Top Tension [mT]"])
            wire2_tens = float(subdict["Wire2 Top Tension [mT]"])
            total_wire_tens = wire1_tens + wire2_tens
        else:
            total_wire_tens = wire1_tens
    else:
        total_wire_tens = 0
            
    bollardPull = subdict["Bollard Pull [mT]"]
    
    if total_wire_tens > AR_Lim:
        lim_warnings += f"AR LIMIT OF {AR_Lim}mT EXCEEDED."
    if bollardPull > BollardPullLim:
        lim_warnings += f"BOLLARD PULL LIMIT OF {BollardPullLim}mT EXCEEDED."
            
    subdict["Warnings"] = lim_warnings
    
    return subdict

def remove_unrelatedDat(
    allDatFiles : list
    ):
    
    def _removeWord(
        oldlist         : list, 
        wordtoRemove    : str
        ):
        
        cleanList = [item for item in oldlist if wordtoRemove not in item]
        return cleanList
    
    cleanedDatList = []   
    # ---- Remove Elements with String at beginning ---- #
    for s in allDatFiles:
        if not s:  # Handle empty strings
            continue
        first_char = s[0]
        if not first_char.isalpha():  # Check if the first character is not a letter
            cleanedDatList.append(s)
            
    # ---- Remove Basefile elements -BuoyYoke,Failed,SurfaceHydro ---- #
    toRemove = ["BuoyYoke", "Failed", "SurfaceHydro", "Interm"]
    for word in toRemove:
        cleanedDatList = _removeWord(cleanedDatList, word)
    
    return cleanedDatList

def rerun_extractResults(
    line_dict   : dict,
    jobpath     : str  
):
    
    print("Looking for .dat files in %s" % jobpath)
    # ------------------- Load vessel JSON ------------- #
    vessel_name = line_dict["vesselGeneral"].get("VesselSelected")
    vessel_name_short   = vessel_name.split()[-1].lower()
    vessel_loc          = os.path.join(constants.VESSEL_DB_DIR, vessel_name_short, f"{vessel_name_short}_coords.json")

    with open (vessel_loc) as json_file:
        vessel_json = json.load(json_file)

    # Simple CLI: work inside the job folder but always restore the working directory
    old_cwd = os.getcwd()
    os.chdir(jobpath)
    try:
        allDatFiles = glob("*.dat")
        allDatFiles = remove_unrelatedDat(allDatFiles)
        allDatFiles = sorted(allDatFiles, key=lambda x: int(x.partition('_')[0]))

        print(allDatFiles)

        print("Extracting results from ready .dat files")

        row = []

        for index, fileName in enumerate(allDatFiles):

            ID = "1"
            extractModel = of.Model(fileName)
            status       = extractModel["General"].Comments

            if index in [0,1]:
                wire_presence = False
            else:
                wire_presence = True

            resDict = extract_StaticRes(fileName, line_dict, ID, status, vessel_json, wire_presence)
            row.append(resDict)
    finally:
        os.chdir(old_cwd)

    df = pd.DataFrame(row)   
    print(df)
    
    return df
    
def rerun_extractMain(
    jsonName        : str, 
    folderName      : str
    ):
    
    with open (jsonName) as json_file:
        line_dict = json.load(json_file)

    jobID      = line_dict["General"].get("jobID")
    jobpath    = folderName

    df1 = rerun_extractResults(line_dict, jobpath)   

    # -------------- Export results to pandas and excel --------------- #
    df1["Wire1 Length [m]"]     = df1["Wire1 Length [m]"].replace("N/A", 0)
    df1["Wire1 Length [m]"]     = pd.to_numeric(df1["Wire1 Length [m]"] )
    df1["Wire Payout [m]"]      = df1["Wire1 Length [m]"].diff().round(1)
    df1["Vessel Movement [m]"]  = df1["Vessel X [m]"].diff().round(1)
    print(df1)
    excel_file_save = jobID.rsplit(".", 1)[0] + "_StaticResults.xlsx"
    print("Saving static results to Excel File: %s" % excel_file_save)
    df1.to_excel("%s\%s" % (jobpath, excel_file_save), sheet_name = "StaticResults")

    
    # ------ Format Laytable ----- #
    # Simple CLI: the template is optional (Google Sheet in the original tool)
    laytable_base = constants.LAYTABLE_TEMPLATE
    laytableSave  = jobID.rsplit(".", 1)[0] + "_Laytable.xlsx"
    savePath      = "%s\%s" % (jobpath, laytableSave)

    if not os.path.exists(laytable_base):
        print(f"NOTE: lay table template not found ({laytable_base}); only {excel_file_save} was written.")
        return df1

    format_laytable(
        laytable_base,
        savePath,
        df1,
        line_dict
    )

    print("Saving static results to Laytable: %s" % laytableSave)
    return df1
    
