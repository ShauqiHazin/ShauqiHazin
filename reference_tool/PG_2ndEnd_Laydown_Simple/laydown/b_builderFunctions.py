import os
import json
import math
import time
import OrcFxAPI as of

from . import utils
from . import constants

from scipy import optimize
import numpy as np
import pandas as pd

'''
Script      :   b_builderFunctions.py

Function    :   Contains functions that serve the following purposes:
                * build linetype (pipe and AR wire)
                * produce a simple mesh for the lines
                * build the 2nd End structure
                * calculate hydrodynamic properties of the structure and buoys
                * create basic catenary shape for the pipe
                
Dependents  :   * a_buildSequence.py
                * c_sequenceFunctions.py
                
Last update :   22 April 2026
Author      :   S.O
'''

def fudge_staticParam(
    model           : object, 
    damping_param   : list
    ):
    '''
    Function    :   Sets the model static parameters
    
    Arguments   :   -model (obj), 
                    -damping_param (list: [min damping, max damping])
    
    Returns     :   modified model obj
    '''
    
    # Model Fudging to aid Convergence
    model["General"].ImplicitUseVariableTimeStep = 'Yes'
    model["General"].StaticsMaxIterations = 1500
    model["General"].StaticsMinDamping = damping_param[0] 
    model["General"].StaticsMaxDamping = damping_param[1] 
    model["General"].ImplicitVariableMaxTimeStep = 0.05
    model["General"].ImplicitVariableMaxNumOfIterations = 100
    model["General"].BuoysIncludedInStatics = "Individually specified"
    
    return model

def add_PalletObject(
    model_pal: object, 
    line_dict: dict
    ):
    
    '''
    Function    :   Add the Pallet object into the relevant step
    
    Args        :   -model_pal (the model you want to add the pallet in)
                    -line_dict (the job dict)
                    
    Returns     :   The modified model with the pallet added.
    '''
    
    vesselSelected = line_dict["vesselGeneral"].get("VesselSelected")
    
    pallet = model_pal.CreateObject(of.ObjectType.Shape, "Pallet")    
    pallet.ShapeType = "Elastic Solid"
    pallet.Shape     = "Block"
    
    pallet.NormalStiffness = 200e3
    # Drawing
    pallet.OutsidePenWidth  = 1
    pallet.OutsidePenColour = 0X0053ff #
    pallet.NumberOfLines    = 50
            
    # Geometry and Origin - Vessel Dependent
    
    if vesselSelected == "Seven Vega":
        pallet.Connection = "Vega-Ramp"
        pallet.OriginX    = 1.0
        pallet.OriginY    = -1.5
        pallet.OriginZ    = 2.3
        pallet.Rotation1  = 0.0
        pallet.Rotation2  = 90.0
        pallet.Rotation3  = 0.0
        #
        pallet.SizeX      = 1.0
        pallet.SizeY      = 3.0
        pallet.SizeZ      = 6.72
    
    if vesselSelected == "Seven Oceans":
        pallet.Connection = "Oceans-Ramp"
        pallet.OriginX    = 1.7398
        pallet.OriginY    = -1.5
        pallet.OriginZ    = 3.387
        pallet.Rotation1  = 0.0
        pallet.Rotation2  = 90.0
        pallet.Rotation3  = 0.0
        #
        pallet.SizeX      = 1.0
        pallet.SizeY      = 3.0
        pallet.SizeZ      = 6.72
        
    if vesselSelected == "Seven Navica":
        pallet.Connection = "Navica-Ramp"
        pallet.OriginX    = -0.2
        pallet.OriginY    = -2.5
        pallet.OriginZ    = 4.04
        pallet.Rotation1  = 0.0
        pallet.Rotation2  = 90.0
        pallet.Rotation3  = 0.0
        #
        pallet.SizeX      = 1.0
        pallet.SizeY      = 5.0
        pallet.SizeZ      = 6.72
            
    return model_pal

def add_PLETContacts(
    model_pal: object, 
    line_dict: dict
    ):
    
    '''
    Function    :   Add the contact objects (6d buoys) to the PLET to make contact with the Pallet
    
    Args        :   -model_pal (the model you want to add the pallet in)
                    -line_dict (the job dict)
                    
    Returns     :   The modified model with the contact added.
    '''
    
    vesselSelected = line_dict["vesselGeneral"].get("VesselSelected")
    # Required info to build model
    plet_option = line_dict["structureGeneral"].get("PLETModellingOpt")
    
    if vesselSelected == "Seven Vega":
        palletW = 3.0
        palletH = 1.0
    elif vesselSelected == "Seven Oceans":
        palletW = 3.0
        palletH = 1.0
    elif vesselSelected == "Seven Navica":
        palletW = 3.0
        palletH = 1.0
    
    # PLET or Mudmat Dimensions
    if plet_option == "Frame only":
        pletL = line_dict["structureGeneral"].get("Frame_Length")
        pletW = line_dict["structureGeneral"].get("Frame_Width")
        pletH = line_dict["structureGeneral"].get("Frame_Height")
        
    elif plet_option == "Frame & Mudmat (With Wings)":
        pletL = line_dict["structureGeneral"].get("Frame_Length_WingUp")
        pletW = line_dict["structureGeneral"].get("Frame_Width_WingUp")
        pletH = line_dict["structureGeneral"].get("Frame_Height_WingUp")
        
    else:
        pletL = line_dict["structureGeneral"].get("Mudmat_Length_WingDown")
        pletW = line_dict["structureGeneral"].get("Mudmat_Width_WingDown")
        pletH = line_dict["structureGeneral"].get("Mudmat_Height_WingDown")
        
    # Contact Pad Sizes
    padL = 0.5*pletL*0.75
    padW = min(0.7*pletW, 0.9*palletW)
            
    # Build Contact_1 and Contact_2
    
    contact_1 = model_pal.CreateObject(of.ObjectType.Buoy6D, "Contact_1")
    contact_1.BuoyType   = "Lumped buoy"
    contact_2 = model_pal.CreateObject(of.ObjectType.Buoy6D, "Contact_2")
    contact_2.BuoyType   = "Lumped buoy"
       
    if plet_option == "Frame only" or "Frame & Mudmat (With Wings)":
        contact_1.Connection = "PLET_Frame"
        contact_2.Connection = "PLET_Frame"
    elif plet_option == "Frame & Mudmat (No Wings)":
        contact_1.Connection = "Mudmat"
        contact_2.Connection = "Mudmat"
        
    ##################################################
    
    contact_1.Mass       = 0.001
    contact_1.MassMomentOfInertiaX = 0.0
    contact_1.MassMomentOfInertiaY = 0.0
    contact_1.MassMomentOfInertiaZ = 0.0
    contact_1.TotalContactArea     = 30.0
    contact_1.Volume               = 0.0
    contact_1.Height               = 0.1
    # Drawing
    contact_1.PenColour = 0xff0000     #"Red"
    contact_1.NumberOfVertices = 8
    # Location
    contact_1.InitialX = 0 #(0.25)*pletL
    contact_1.InitialY = 0
    contact_1.InitialZ = -(0.5)*pletH
    contact_1.InitialRotation2 = 0.0
    # Vertices
    contact_1.VertexX[0] = (0.25)*pletL - (0.5)*padL
    contact_1.VertexX[1] = (0.25)*pletL + (0.5)*padL
    contact_1.VertexX[2] = (0.25)*pletL + (0.5)*padL
    contact_1.VertexX[3] = (0.25)*pletL - (0.5)*padL
    contact_1.VertexX[4] = (0.25)*pletL - (0.5)*padL
    contact_1.VertexX[5] = (0.25)*pletL + (0.5)*padL
    contact_1.VertexX[6] = (0.25)*pletL + (0.5)*padL
    contact_1.VertexX[7] = (0.25)*pletL - (0.5)*padL
    #
    contact_1.VertexY[0] = (0.5)*padW
    contact_1.VertexY[1] = (0.5)*padW
    contact_1.VertexY[2] = -(0.5)*padW
    contact_1.VertexY[3] = -(0.5)*padW
    contact_1.VertexY[4] = (0.5)*padW
    contact_1.VertexY[5] = (0.5)*padW
    contact_1.VertexY[6] = -(0.5)*padW
    contact_1.VertexY[7] = -(0.5)*padW
    #
    contact_1.VertexZ[0] = 0.1 
    contact_1.VertexZ[1] = 0.1 
    contact_1.VertexZ[2] = 0.1 
    contact_1.VertexZ[3] = 0.1 
    contact_1.VertexZ[4] = 0.0 
    contact_1.VertexZ[5] = 0.0 
    contact_1.VertexZ[6] = 0.0 
    contact_1.VertexZ[7] = 0.0
    
    ######
        
    contact_2.Mass       = 0.001
    contact_2.MassMomentOfInertiaX = 0.0
    contact_2.MassMomentOfInertiaY = 0.0
    contact_2.MassMomentOfInertiaZ = 0.0
    contact_2.TotalContactArea     = 30.0
    contact_2.Volume               = 0.0
    contact_2.Height               = 0.1
    # Drawing
    contact_2.PenColour = 0xff0000    #"Red"
    contact_2.NumberOfVertices = 8
    # Location
    contact_2.InitialX = 0 #(0.25)*pletL
    contact_2.InitialY = 0
    contact_2.InitialZ = -(0.5)*pletH
    contact_2.InitialRotation2 = 0.0
    # Vertices
    contact_2.VertexX[0] = -(0.25)*pletL - (0.5)*padL
    contact_2.VertexX[1] = -(0.25)*pletL + (0.5)*padL
    contact_2.VertexX[2] = -(0.25)*pletL + (0.5)*padL
    contact_2.VertexX[3] = -(0.25)*pletL - (0.5)*padL
    contact_2.VertexX[4] = -(0.25)*pletL - (0.5)*padL
    contact_2.VertexX[5] = -(0.25)*pletL + (0.5)*padL
    contact_2.VertexX[6] = -(0.25)*pletL + (0.5)*padL
    contact_2.VertexX[7] = -(0.25)*pletL - (0.5)*padL
    #
    contact_2.VertexY[0] = (0.5)*padW
    contact_2.VertexY[1] = (0.5)*padW
    contact_2.VertexY[2] = -(0.5)*padW
    contact_2.VertexY[3] = -(0.5)*padW
    contact_2.VertexY[4] = (0.5)*padW
    contact_2.VertexY[5] = (0.5)*padW
    contact_2.VertexY[6] = -(0.5)*padW
    contact_2.VertexY[7] = -(0.5)*padW
    #
    contact_2.VertexZ[0] = 0.1 
    contact_2.VertexZ[1] = 0.1 
    contact_2.VertexZ[2] = 0.1 
    contact_2.VertexZ[3] = 0.1   
    contact_2.VertexZ[4] = 0.0 
    contact_2.VertexZ[5] = 0.0 
    contact_2.VertexZ[6] = 0.0 
    contact_2.VertexZ[7] = 0.0
                 
    #
        
    return model_pal
        
def create_linetype(
    model       : object, 
    line        : object, 
    line_dict   : dict
    ):
    '''
    Function    :   Create linetype(s), create single linetype for single pipe, and three knetypes for pipe-in-pipe(outer, inner, equivalent)
    
    Args        :   -model (the model you want to add the line in)
                    -line (the line)
                    -line_dict (the job dict)
                    
    Returns     :   The modified model with the contact added.
    '''
    ## Check What is Needed for Clamped Step
    modelSJatClamp = line_dict["sequenceGeneral"].get("Pipe_ClampSJ")
    
    ## Check if Single pipe or pipe-in-pipe
    if line_dict["pipeGeneral"].get("PipeType") == "Pipe-in-Pipe":
        linetypeName_outer = line_dict["pipeGeneral"].get("Pipe1")
        linetypeObjs_outer = line_dict[linetypeName_outer]
        linetype_outer = model.CreateObject(
            of.otLineType, linetypeObjs_outer["Name"]
        )
        linetype_outer.Category = "Homogeneous pipe"

        linetype_outer.E = linetypeObjs_outer[
            "E"
        ]*1e3  ## Note that Non-Linear stress-strain is not possible for equivalent linetypes in Orcaflex

        linetype_outer.ID = linetypeObjs_outer["ID"]*0.001
        linetype_outer.OD = linetypeObjs_outer["OD"]*0.001
        linetype_outer.MaterialDensity  = linetypeObjs_outer["MaterialDensity"]
        linetype_outer.CoatingThickness = linetypeObjs_outer["CoatingThickness"]*0.001
        if linetype_outer.CoatingThickness > 0:
            linetype_outer.CoatingMaterialDensity = linetypeObjs_outer[
                "CoatingMaterialDensity"
            ]

        linetype_outer.Cdx = linetypeObjs_outer["Cdx"]
        linetype_outer.Cax = linetypeObjs_outer["Cax"]
        linetype_outer.SeabedNormalFrictionCoefficient = linetypeObjs_outer[
            "SeabedFrictionCoeff_Normal"
        ]
        linetype_outer.SeabedAxialFrictionCoefficient = linetypeObjs_outer[
            "SeabedFrictionCoeff_Axial"
        ]

        # 2. Inner 'Secondary' linetype

        linetypeName_inner = line_dict["pipeGeneral"].get("Pipe2")
        linetypeObjs_inner = line_dict[linetypeName_inner]
        linetype_inner = model.CreateObject(
            of.otLineType, linetypeObjs_inner["Name"]
        )

        E_inner = linetypeObjs_inner[
            "E"
        ]*1e3  ## Note that Non-Linear stress-strain is not possible for equivalent linetypes in Orcaflex
        poiss_inner = linetypeObjs_inner["Poissons_ratio"]

        if linetypeObjs_inner["CRALiningThickness"] != 0:
            t_liner_inner = linetypeObjs_inner["CRALiningThickness"]*0.001
            rho_liner_inner = linetypeObjs_inner["CRALiningMaterialDensity"]
        else:
            t_liner_inner   = 0
            rho_liner_inner = 0

        # Category Tab
        linetype_inner.Category = "General"

        # Geometry & Mass tab
        ID_steel_inner = linetypeObjs_inner["ID"]*0.001
        OD_steel_inner = linetypeObjs_inner["OD"]*0.001
        rho_steel_inner = linetypeObjs_inner["MaterialDensity"]

        t_annulus = linetypeObjs_inner["AnnulusThickness"]*0.001
        ID_annulus = OD_steel_inner
        OD_annulus = ID_annulus + 2 * t_annulus
        rho_annulus = linetypeObjs_inner["AnnulusDensity"]

        centraliser_spacing = linetypeObjs_inner["CentraliserSpacing"]
        centraliser_mass = linetypeObjs_inner["CentraliserMass"]
        centraliser_massperunitL = centraliser_mass / centraliser_spacing

        linetype_inner.ID = ID_steel_inner
        linetype_inner.OD = OD_annulus
        linetype_inner.MassPerUnitLength = (
            math.pi
            / 4
            * (
                (OD_steel_inner**2 - ID_steel_inner**2) * rho_steel_inner
                + (OD_annulus**2 - ID_annulus**2) * rho_annulus
                + (ID_steel_inner**2 - (ID_steel_inner - 2 * t_liner_inner) ** 2)
                * rho_liner_inner
            )
            + centraliser_massperunitL
        )

        # Structure Tab
        linetype_inner.EIx = (
            E_inner * math.pi / 64 * (OD_steel_inner**4 - ID_steel_inner**4)
        )
        linetype_inner.EA = (
            E_inner * math.pi / 4 * (OD_steel_inner**2 - ID_steel_inner**2)
        )
        linetype_inner.GJ = (
            E_inner
            / (2 * (1 + poiss_inner))
            * math.pi
            / 32
            * (OD_steel_inner**4 - ID_steel_inner**4)
        )

        # Drag & lift tab
        linetype_inner.Cdx = linetypeObjs_inner["Cdx"]
        linetype_inner.Cax = linetypeObjs_inner["Cax"]
        # Stress Tab
        linetype_inner.StressID = ID_steel_inner
        linetype_inner.StressOD = OD_steel_inner
        # Friction Tab
        linetype_inner.SeabedNormalFrictionCoefficient = linetypeObjs_inner[
            "SeabedNormalFrictionCoefficient"
        ]
        linetype_inner.SeabedAxialFrictionCoefficient = linetypeObjs_inner[
            "SeabedAxialFrictionCoefficient"
        ]

        # 3. 'Equivalent' linetype
        linetypeName_equiv = line_dict["pipeGeneral"].get("LineTypeName")
        linetype_equiv = model.CreateObject(of.otLineType, linetypeName_equiv)
        linetype_equiv.Category = "Equivalent line"
        linetype_equiv.Carrier = linetypeName_outer
        linetype_equiv.NumberOfSecondaryLines = 1
        linetype_equiv.SecondaryLineType[0] = linetypeName_inner
        linetype_equiv.SecondaryLineLocation[0] = "Internal"
        linetype_equiv.SecondaryContentsDensity[0] = 1.025
        linetype_equiv.SecondaryContributesToAxialStiffness[0] = "No"
        linetype_equiv.SecondaryContributesToBendingStiffness[0] = "Yes"
        linetype_equiv.SecondaryContributesToTorsionalStiffness[0] = "No"
        linetype_equiv.Cdx = linetypeObjs_outer["Cdx"]
        linetype_equiv.Cax = linetypeObjs_outer[
            "Cax"
        ]  # Setting Cdx/Cax same as outer pipe
        linetype = linetype_equiv

    else:  # Create Single pipe linetype
        linetypeName = line_dict["pipeGeneral"].get("Pipe1")
        linetypeObjs = line_dict[linetypeName]
        linetype = model.CreateObject(of.otLineType, linetypeObjs["Name"])
        linetype.Category = linetypeObjs["Category"]  #homog

        if linetypeObjs["StressStrainRelationship"] == "Ramberg-Osgood":
            StressStrainName = linetypeObjs["StressStrain_Name"]
            vardata = model.CreateObject(
                of.otStressStrainRelationship, StressStrainName
            )
            vardata.Name = StressStrainName
            vardata.CurveType = linetypeObjs["StressStrain_CurveType"]
            vardata.E = linetypeObjs["StressStrain_E"]*1e3
            vardata.RefStress = linetypeObjs["StressStrain_RefStress"]*1e3
            vardata.K = linetypeObjs["StressStrain_K"]
            vardata.n = linetypeObjs["StressStrain_n"]
            linetype.E = StressStrainName
        else:
            linetype.E = linetypeObjs["E"]*1e3

        linetype.OD = linetypeObjs["OD"]*0.001
        linetype.ID = linetypeObjs["ID"]*0.001
        linetype.MaterialDensity = linetypeObjs["MaterialDensity"]
        linetype.CoatingThickness = linetypeObjs["CoatingThickness"]*0.001
        if linetype.CoatingThickness > 0:
            linetype.CoatingMaterialDensity = linetypeObjs["CoatingMaterialDensity"]

        if linetypeObjs["CRALiningThickness"] != 0:
            linetype.LiningThickness = linetypeObjs["CRALiningThickness"]*0.001
            linetype.LiningMaterialDensity = linetypeObjs["CRALiningMaterialDensity"]
            # If CRA is accounted for in DNV calculations:
            linetype.DNVSTF101TCRA  = linetypeObjs["DNV_tCRA"]/ 1000.
            linetype.DNVSTF101FyCRA = linetypeObjs["SMYS_CRA"]* 1e3
            linetype.DNVSTF101FuCRA = linetypeObjs["SMTS_CRA"]* 1e3

        linetype.Cdx = linetypeObjs["Cdx"]
        linetype.SeabedNormalFrictionCoefficient = linetypeObjs[
            "SeabedFrictionCoeff_Normal"
        ]
        linetype.SeabedAxialFrictionCoefficient = linetypeObjs[
            "SeabedFrictionCoeff_Axial"
        ]

        linetype.DNVOSF101Fy        = linetypeObjs["SMYS"] * 1e3  ## Converted from MPa to kPa
        linetype.DNVOSF101Fu        = linetypeObjs["SMTS"] * 1e3  ## Converted from MPa to kPa
        linetype.DNVOSF101E         = linetypeObjs["DNV_E"] * 1e3
        #linetype.DNVOSF101GammaC  = linetypeObjs["Condition_load_effect_factor"]        
        #
        codeCheck                   = model["Code checks"]
        # DNV ST F101
        try:
            linetype.DNVSTF101Fy        = linetypeObjs["SMYS"] * 1e3  ## Converted from MPa to kPa
            linetype.DNVSTF101Fu        = linetypeObjs["SMTS"] * 1e3  ## Converted from MPa to kPa
            linetype.DNVSTF101E         = linetypeObjs["DNV_E"] * 1e3
            #
            codeCheck.DNVSTF101GammaF    = linetypeObjs["Functional_load_factor_case_a"]
            codeCheck.DNVSTF101GammaE    = linetypeObjs["Environmental_load_factor_case_a"]
            codeCheck.DNVSTF101GammaC    = linetypeObjs["Condition_load_effect_factor"]
            codeCheck.DNVSTF101GammaRF   = 0.0
            #
            linetype.DNVSTF101GammaSCLB = linetypeObjs["Safety_class_resistance_factor"]
            linetype.DNVSTF101GammaM    = linetypeObjs["Material_resistance_factor"]
            linetype.DNVSTF101AlphaFab  = linetypeObjs["Fabrication_factor"]
        
        except:
            linetype.DNVOSF101Fy        = linetypeObjs["SMYS"] * 1e3  ## Converted from MPa to kPa
            linetype.DNVOSF101Fu        = linetypeObjs["SMTS"] * 1e3  ## Converted from MPa to kPa
            linetype.DNVOSF101E         = linetypeObjs["DNV_E"] * 1e3
            #
            codeCheck.DNVOSF101GammaF    = linetypeObjs["Functional_load_factor_case_a"]    
            codeCheck.DNVOSF101GammaE    = linetypeObjs["Environmental_load_factor_case_a"]
            codeCheck.DNVOSF101GammaC    = linetypeObjs["Condition_load_effect_factor"]
            codeCheck.DNVOSF101GammaRF   = 0.0
            #
            linetype.DNVOSF101GammaSC   = linetypeObjs["Safety_class_resistance_factor"]
            linetype.DNVOSF101GammaM    = linetypeObjs["Material_resistance_factor"]
            linetype.DNVOSF101AlphaFab  = linetypeObjs["Fabrication_factor"]
        
        #
        linetype.APIRP1111E = linetypeObjs["DNV_E"] * 1e3
        linetype.APIRP1111S = linetypeObjs["SMYS"] * 1e3
        linetype.APIRP1111U = linetypeObjs["SMTS"] * 1e3
        linetype.APIRP1111Delta = linetypeObjs["Ovality"]

        linetype.APIRP1111Fa = linetypeObjs["Allowable_load_factor"]
        linetype.APIRP1111Fc = linetypeObjs["Collapse_factor"]
        linetype.APIRP1111Fbs = linetypeObjs["Bending_safety_factor"]
        linetype.APIRP1111SAF = linetypeObjs["Strain_amplification_factor"]

        # NOTE: assumed parameters, not user input
        linetype.DNVOSF101AlphaH        = constants.STRAIN_HARDENING_FACTOR
        linetype.DNVOSF101F0            = constants.OUT_OF_ROUNDNESS
        linetype.DNVOSF101GammaEpsilon  = constants.STRAIN_RESISTANCE_FACTOR
        linetype.DNVOSF101AlphaGW       = constants.GIRTH_WELD_FACTOR
        linetype.DNVOSF101AlphaPm       = constants.PLASTIC_MOMENT_REDUCTION
        linetype.DNVOSF101SimplifiedStrainLimit = constants.SIMPLIFIED_STRAIN_LIMIT

    ## Assign linetype and set No. of sections ##
    line.LineType[0] = linetype.Name
    line.NumberOfSections = 6
    
    ## Inc. Torsion
    line.IncludeTorsion = "Yes"
    line.EndAxBendingStiffness = of.OrcinaInfinity()
    line.EndAyBendingStiffness = of.OrcinaInfinity()
    line.EndATwistingStiffness = of.OrcinaInfinity()
    
    # Maybe make this optional?
    line.EndBxBendingStiffness = 0 
    line.EndByBendingStiffness = 0 
    line.EndBTwistingStiffness = 0 
    
    # Set friction
    line.StaticsSeabedFrictionPolicy = "None"
    
    try:
        model.DestroyObject("Line type1")
    except Exception:
        pass  # Delete default linetype (created with line object) if exists in model
    
    ####------------------ Check if SJ required ---------- #
    
    if line_dict["SJGeneral"].get("SJrequired") == True or modelSJatClamp == True:
        
        #############-------------  Assign Stress Joint
        SJlinetype = linetype.CreateClone("StressJoint")
        SJlinetype.OD = float(line_dict["SJGeneral"].get("SJOD"))*0.001
        SJlinetype.PenColour = 0xFF00FF
        SJlinetype.PenWidth  = 5
        
        #############-------------  Assign Transition Joint   
        
        TJlinetype = linetype.CreateClone("TransitionJoint")
        vardataTJ  = model.CreateObject(of.otLineTypeDiameter, "TransitionProfile")
        TJlen   = float(line_dict["SJGeneral"].get("TJLen")) 
        arclen  = [0, TJlen]
        od      = [SJlinetype.OD, linetype.OD]
        vardataTJ.IndependentValue = arclen
        vardataTJ.DependentValue   = od
        TJlinetype.OD = "TransitionProfile"
        TJlinetype.PenColour = 0x800080	
        TJlinetype.PenWidth  = 3
        
        ## Assign linetype and set No. of sections ##
        line.LineType[0] = SJlinetype.Name
        line.LineType[1] = TJlinetype.Name
        line.LineType[2] = linetype.Name
        line.LineType[3] = linetype.Name
        line.LineType[4] = linetype.Name
        line.LineType[5] = linetype.Name
        #
        #if clamped_step:
        #    line.Length[0] = float(lengthSJClamp)
        #else:
        #    line.Length[0] = float(line_dict["SJGeneral"].get("SJLen"))
            
        line.Length[0] = float(line_dict["SJGeneral"].get("SJLen"))
               
def create_lineSimpleMesh(
    line: object
    ):
    '''
    Functions   : take the pipe line and section it into a simple mesh
    
    Args        : line (the line in question)
    
    Returns     : -
    '''   
    secLine = len(line.TargetSegmentLength)
    
    for sec in range(secLine):
        try:
            line.TargetSegmentLength[sec] = 1
        except:
            pass
    
    line.TargetSegmentLength[2] = 1
    line.TargetSegmentLength[3] = 2
    line.TargetSegmentLength[4] = 4    
    line.TargetSegmentLength[5] = 8
        
def calc_hydro_properties_rectangular_plate(
    buoy_length : float,
    buoy_width  : float,
    buoy_height : float,
    wia         : float,
    wiw         : float,
    perf_x      : float,
    perf_y      : float,
    perf_z      : float,
    roW         : float,
    cog_x       : float,
    cog_y       : float,
    cog_z       : float
    ):

    '''
    Description
    ===========
    * This function generates the hydrodynamic properties based on buoy geometry.
    * It assumes that CoG and CoV are the same as simplification.

    Input (args)
    ============
    * buoy_length (float)       : length [m]
    * buoy_width (float)        : width [m]
    * buoy_height (float)       : height [m]
    * wia (float)               : weight in air [Te]
    * wiw (float)               : weight in water [Te]
    * perf_x (float)            : perforation in x direction [%/100]
    * perf_y (float)            : perforation in y direction [%/100]
    * perf_z (float)            : perforation in z direction [%/100]
    * roW (float)               : density of seawater [te/m3]
    * cog_x (float)             : center of gravity x [m]
    * cog_y (float)             : center of gravity y [m]
    * cog_z (float)             : center of gravity z [m]

    Output (returns)
    ================
    * HydroProperties (hydrodynamic properties dict) including:
        wia (float)                        : weight in air [Te]
        wiw (float)                        : weight in water [Te]
        volume (float)                     : volume [m3]
        drag_area_x (float)                : drag area in x direction [m2]
        drag_area_y (float)                : drag area in y direction [m2]
        drag_area_z (float)                : drag area in z direction [m2]
        cd_splash_x (float)                : drag coefficient in x direction for splash zone [-]
        cd_splash_y (float)                : drag coefficient in y direction for splash zone[-]
        cd_splash_z (float)                : drag coefficient in z direction for splash zone[-]
        cd_deep_x (float)                  : drag coefficient in x direction for deep zone[-]
        cd_deep_y (float)                  : drag coefficient in y direction for deep zone[-]
        cd_deep_z (float)                  : drag coefficient in z direction for deep zone[-]
        Ca_adjusted_x (float)              : adjusted added mass coefficient in x direction [-]
        Ca_adjusted_y (float)              : adjusted added mass coefficient in y direction [-]
        Ca_adjusted_z (float)              : adjusted added mass coefficient in z direction [-]
        mass_inertia_x (float)             : mass moment of inertia in x direction [Te.m2]
        mass_inertia_y (float)             : mass moment of inertia in y direction [Te.m2]
        mass_inertia_z (float)             : mass moment of inertia in z direction [Te.m2]
        added_mass_x (float)               : added mass in x direction [Te]
        added_mass_y (float)               : added mass in y direction [Te]
        added_mass_z (float)               : added mass in z direction [Te]
        drag_moment_area_splash_x (float)  : drag moment of area in x direction for splash zone [m5]
        drag_moment_area_splash_y (float)  : drag moment of area in y direction for splash zone [m5]
        drag_moment_area_splash_z (float)  : drag moment of area in z direction for splash zone [m5]
        drag_moment_area_deep_x (float)    : drag moment of area in x direction for deep zone [m5]
        drag_moment_area_deep_y (float)    : drag moment of area in y direction for deep zone [m5]
        drag_moment_area_deep_z (float)    : drag moment of area in z direction for deep zone [m5]
        drag_mom_coef_x (float)            : drag moment coefficient in x direction [-]
        drag_mom_coef_y (float)            : drag moment coefficient in y direction [-]
        drag_mom_coef_z (float)            : drag moment coefficient in z direction [-]
        hydro_inertia_x (float)            : hydrodynamic inertia in x direction [Te.m2]
        hydro_inertia_y (float)            : hydrodynamic inertia in y direction [Te.m2]
        hydro_inertia_z (float)            : hydrodynamic inertia in z direction [Te.m2]
        inertia_coef_x (float)             : inertia coefficient in x direction [-]
        inertia_coef_y (float)             : inertia coefficient in y direction [-]
        inertia_coef_z (float)             : inertia coefficient in z direction [-]
    '''

    # Performs hydrodynamic coefficients calculations as per DNVGL-RP-N103
    volume = (wia - wiw) / roW
    area_z = buoy_length * buoy_width * (1 - perf_z)
    buoyancy = roW * 9.80665 * volume

    # Constants according to DNVGL-RP-N103 
    # Table A-2 Analytical added mass coefficient for three­dimensional bodies in infinite fluid
    length_over_width_ratio = [1,1.2,1.25,1.33,1.5,1.59,2,2.5,3,3.17,4,5,6.25,8,10,1e3]
    Ca = [0.579,0.63,0.642,0.66,0.690,0.704,0.757,0.801,0.830,0.840,0.872,0.897,0.917,0.934,0.947,1.000]
    
    # Table B-2 Drag coefficient on three­dimensional objects for steady flow CDS 
    # Rectangular plate normal to flow direction
    length_over_height_ratio = [1,5,10,11,100,1000,10000]
    Cds_rect = [1.16,1.20,1.50,1.90,1.90,1.90,1.90]

    # Prism
    length_over_width_ratio_cd = [1,1.5,2,2.5,3,4,5]
    Cds_prism = [1.15,0.97,0.87,0.9,0.93,0.95,0.95]

    # Newman's coefficients
    ba_ratio = [0,0.02,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0,1.1,1.2,1.3,1.4,1.5,1.6]
    m_55_upper = [1,0.99,0.89,0.7,0.525,0.37,0.24,0.15,0.065,0.03,0.01,0,0.01,0.025,0.045,0.075,0.1,0.125]
    m_55_lower = [0.21,0.21,0.205,0.19,0.155,0.13,0.1,0.07,0.045,0.02,0.005,0,0.005,0.03,0.055,0.14,0.225,0.35]

    # 6th degree fitting
    #m_55_upper_fitting = np.poly1d(np.polyfit(ba_ratio, m_55_upper, 6))
    #m_55_lower_fitting = np.poly1d(np.polyfit(ba_ratio, m_55_lower, 6))
    m_55_upper_fitting = lambda x: -0.8958*x**6 + 5.1304*x**5 - 11.616*x**4 + 12.599*x**3 - 5.3891*x**2 - 0.8306*x + 1.0056
    m_55_lower_fitting = lambda x: -0.2602*x**6 + 1.3492*x**5 - 2.5645*x**4 + 2.6105*x**3 - 1.4314*x**2 + 0.086*x + 0.2094

    # Calculate hydrodynamic properties in X direction
    a = min(buoy_width, buoy_height)
    b = max(buoy_width, buoy_height)
    c = buoy_length

    # Assess reduction of added mass due to perforation in X direction
    if perf_x <= 0.05:
        perfuration_x_factor = 1
    elif perf_x < 0.34:
        perfuration_x_factor = 0.7 + 0.3 * math.cos(math.pi * (perf_x*100 - 5)/34)
    elif perf_x <= 0.50:
        perfuration_x_factor = math.exp((10 - perf_x*100)/28)
    else:
        perfuration_x_factor = 0.25
        
    # Calculate corrected added mass coefficient in X direction
    ca_struct_x = np.interp(b/a, length_over_width_ratio, Ca)
    
    # Calculate lambda factor to account for the "wall" effect
    lambda_fact = (math.sqrt(a * b) ) / ( c + math.sqrt(a * b) )

    # Calculate volume of reference in X direction
    vol_ref_x = (math.pi/4) * (a**2) * b

    # Calculate added mass in X direction
    added_mass_x = vol_ref_x * ca_struct_x * roW * (1 + math.sqrt( (1 - lambda_fact ** 2) / (2 * (1 + lambda_fact ** 2) ) ) )
    
    # Adjust added mass with the perfuration
    added_mass_x = added_mass_x * perfuration_x_factor

    # Calculate adjusted added mass coefficient
    ca_adjust_x = ( added_mass_x ) / ( roW * volume )

    # Calculate drag area in X direction
    drag_area_x = buoy_width * buoy_height * (1 - perf_x)

    # Calculate drag coefficient 
    if c / math.sqrt(a * b) < 1:
        #cd_deep_x = np.interp(b / a, length_over_height_ratio, Cds_rect)
        cd_deep_x = np.interp(c / math.sqrt(a * b), length_over_height_ratio, Cds_rect)
    else:
        #cd_deep_x = np.interp(c / math.sqrt(a * b), length_over_width_ratio_cd, Cds_prism)
        cd_deep_x = np.interp(c / a, length_over_width_ratio_cd, Cds_prism)

    if 3 * cd_deep_x > 2.5:
        cd_splash_x = 3 * cd_deep_x
    else:
        cd_splash_x = 2.5
        
    # Calculate hydrodynamic properties in Y direction
    a = min(buoy_length,buoy_height)
    b = max(buoy_length,buoy_height)
    c = buoy_width

    # Assess reduction of added mass due to perforation in Y direction
    if perf_y <= 0.05:
        perfuration_y_factor = 1
    elif perf_y < 0.34:
        perfuration_y_factor = 0.7 + 0.3 * math.cos(math.pi * (perf_y*100 - 5)/34)
    elif perf_y <= 0.50:
        perfuration_y_factor = math.exp((10 - perf_y*100)/28)
    else:
        perfuration_y_factor = 0.25

    # Calculate corrected added mass coefficient in Y direction
    ca_struct_y = np.interp(b/a, length_over_width_ratio, Ca)

    # Calculate lambda factor to account for the "wall" effect
    lambda_fact = (math.sqrt(a*b))/(c + math.sqrt(a*b))

    # Calculate volume of reference in Y direction
    vol_ref_y = (math.pi/4) * (a**2) * b

    # Calculate added mass in Y direction
    added_mass_y = vol_ref_y * ca_struct_y * roW * (1 + math.sqrt((1-lambda_fact**2)/(2*(1+lambda_fact**2))))

    # Adjust added mass with the perfuration
    added_mass_y = added_mass_y * perfuration_y_factor

    # Calculate adjusted added mass coefficient
    ca_adjust_y = (added_mass_y) / (roW * volume)

    # Calculate drag area in Y direction
    drag_area_y = buoy_length * buoy_height * (1 - perf_y)

    # Calculate drag coefficient 
    if c / math.sqrt(a*b) < 1:
        cd_deep_y = np.interp(b/a,length_over_height_ratio,Cds_rect)
    else:
        #cd_deep_y = np.interp(c/math.sqrt(a*b),length_over_width_ratio_cd,Cds_prism)
        cd_deep_y = np.interp(b/a, length_over_width_ratio_cd, Cds_prism)

    if 3 * cd_deep_y > 2.5:
        cd_splash_y = 3 * cd_deep_y
    else:
        cd_splash_y = 2.5

    # Calculate hydrodynamic properties in Z direction
    a = min(buoy_width,buoy_length)
    b = max(buoy_width,buoy_length)
    c = buoy_height

    # Assess reduction of added mass due to perforation in Z direction
    if perf_z <= 0.05:
        perfuration_z_factor = 1
    elif perf_z < 0.34:
        perfuration_z_factor = 0.7 + 0.3 * math.cos(math.pi * (perf_z*100 - 5)/34)
    elif perf_z <= 0.50:
        perfuration_z_factor = math.exp((10 - perf_z*100)/28)
    else:
        perfuration_z_factor = 0.25

    # Calculate corrected added mass coefficient in Z direction
    ca_struct_z = np.interp(b/a,length_over_width_ratio,Ca)

    # Calculate lambda factor to account for the "wall" effect
    lambda_fact = (math.sqrt(a*b))/(c + math.sqrt(a*b))

    # Calculate volume of reference in Y direction
    vol_ref_z = (math.pi/4) * (a**2) * b

    # Calculate added mass in Z direction
    added_mass_z = vol_ref_z * ca_struct_z * roW * (1 + math.sqrt((1-lambda_fact**2)/(2*(1+lambda_fact**2))))

    # Adjust added mass with the perfuration
    added_mass_z = added_mass_z * perfuration_z_factor

    # Calculate adjusted added mass coefficient
    ca_adjust_z = (added_mass_z) / (roW*volume)

    # Calculate drag area in Z direction
    drag_area_z = buoy_width * buoy_length * (1 - perf_z)

    # Calculate drag coefficient
    if c / math.sqrt(a*b) < 1:
        cd_deep_z = np.interp(b/a,length_over_height_ratio,Cds_rect)
    else:
        #cd_deep_z = np.interp(c/math.sqrt(a*b),length_over_width_ratio_cd,Cds_prism)
        cd_deep_z = np.interp(b/a, length_over_width_ratio_cd, Cds_prism)

    if 3 * cd_deep_z > 2.5:
        cd_splash_z = 3 * cd_deep_z
    else:
        cd_splash_z = 2.5

    # Calculate Mass moment of Inertia including parallel axis theorem
    mass_moment_inertia_x = (wia/12) * (buoy_width**2 + buoy_height**2) + wia * (cog_y**2 + cog_z**2)
    mass_moment_inertia_y = (wia/12) * (buoy_length**2 + buoy_height**2) + wia * (cog_x**2 + cog_z**2)
    mass_moment_inertia_z = (wia/12) * (buoy_length**2 + buoy_width**2) + wia * (cog_x**2 + cog_y**2)
    
    # Calculate Rotational properties for splash zone and deep
    drag_moment_area_splash_x = (1/32) * (cd_splash_y * buoy_length * buoy_height**4 + cd_splash_z * buoy_length * buoy_width**4) 
    drag_moment_area_splash_y = (1/32) * (cd_splash_x * buoy_width * buoy_height**4 + cd_splash_z * buoy_width * buoy_length**4)
    drag_moment_area_splash_z = (1/32) * (cd_splash_x * buoy_height * buoy_width**4 + cd_splash_y * buoy_height * buoy_length**4)

    drag_moment_area_deep_x = (1/32) * (cd_deep_y * buoy_length * buoy_height**4 + cd_deep_z * buoy_length * buoy_width**4) 
    drag_moment_area_deep_y = (1/32) * (cd_deep_x * buoy_width * buoy_height**4 + cd_deep_z * buoy_width * buoy_length**4)
    drag_moment_area_deep_z = (1/32) * (cd_deep_x * buoy_height * buoy_width**4 + cd_deep_y * buoy_height * buoy_length**4)

    # Set drag moment coefficient as 1
    drag_mom_x_coef = 1
    drag_mom_y_coef = 1
    drag_mom_z_coef = 1

    # Calculate the hydrodynamic inertia
    hydro_inertia_x = (1/12) * volume * roW * (buoy_width**2 + buoy_height**2)
    hydro_inertia_y = (1/12) * volume * roW * (buoy_length**2 + buoy_height**2)
    hydro_inertia_z = (1/12) * volume * roW * (buoy_length**2 + buoy_width**2)

    # Calculate inertia coefficient according to Newman's book
    # Direction X
    a_x = buoy_length / 2
    b_x = math.sqrt ( buoy_width * buoy_height / math.pi )

    ratio_b_over_a = b_x / a_x
    ratio_a_over_b = a_x / b_x

    if ratio_b_over_a < 1.6:
        inertia_coef_x = m_55_upper_fitting(ratio_b_over_a)
    else:
        inertia_coef_x = m_55_lower_fitting(ratio_a_over_b) * ( (2 * b_x**3) / ( a_x * ( a_x**2 + b_x **2 ) ) )

    # Direction Y
    a_x = buoy_width / 2
    b_x = math.sqrt ( buoy_length * buoy_height / math.pi )

    ratio_b_over_a = b_x / a_x
    ratio_a_over_b = a_x / b_x

    if ratio_b_over_a < 1.6:
        inertia_coef_y = m_55_upper_fitting(ratio_b_over_a)
    else:
        inertia_coef_y = m_55_lower_fitting(ratio_a_over_b) * ( (2 * b_x**3) / ( a_x * ( a_x**2 + b_x **2 ) ) )

    # Direction Z
    a_x = buoy_height / 2
    b_x = math.sqrt ( buoy_width * buoy_length / math.pi )

    ratio_b_over_a = b_x / a_x
    ratio_a_over_b = a_x / b_x

    if ratio_b_over_a < 1.6:
        inertia_coef_z = m_55_upper_fitting(ratio_b_over_a)
    else:
        inertia_coef_z = m_55_lower_fitting(ratio_a_over_b) * ( (2 * b_x**3) / ( a_x * ( a_x**2 + b_x **2 ) ) )

    # Assembly in a dictionary
    labels = [  'weight_in_air',
                'weight_in_water',
                'volume',
                'drag_area_x',
                'drag_area_y',
                'drag_area_z',
                'cd_splashzone_x',
                'cd_splashzone_y',
                'cd_splashzone_z',
                'cd_deep_x',
                'cd_deep_y',
                'cd_deep_z',
                'ca_adjusted_x',
                'ca_adjusted_y',
                'ca_adjusted_z',
                'mass_inertia_x',
                'mass_inertia_y',
                'mass_inertia_z',
                'added_mass_x',
                'added_mass_y',
                'added_mass_z',
                'drag_moment_area_splash_x',
                'drag_moment_area_splash_y',
                'drag_moment_area_splash_z',
                'drag_moment_area_deep_x',
                'drag_moment_area_deep_y',
                'drag_moment_area_deep_z',
                'drag_mom_coef_x',
                'drag_mom_coef_y',
                'drag_mom_coef_z',
                'hydro_inertia_x',
                'hydro_inertia_y',
                'hydro_inertia_z',
                'inertia_coef_x',
                'inertia_coef_y',
                'inertia_coef_z'
                ]

    values = [  wia,
                wiw,
                volume,
                drag_area_x,
                drag_area_y,
                drag_area_z,
                cd_splash_x,
                cd_splash_y,
                cd_splash_z,
                cd_deep_x,
                cd_deep_y,
                cd_deep_z,
                ca_adjust_x,
                ca_adjust_y,
                ca_adjust_z,
                mass_moment_inertia_x,
                mass_moment_inertia_y,
                mass_moment_inertia_z,
                added_mass_x,
                added_mass_y,
                added_mass_z,
                drag_moment_area_splash_x,
                drag_moment_area_splash_y,
                drag_moment_area_splash_z,
                drag_moment_area_deep_x,
                drag_moment_area_deep_y,
                drag_moment_area_deep_z,
                drag_mom_x_coef,
                drag_mom_y_coef,
                drag_mom_z_coef,
                hydro_inertia_x,
                hydro_inertia_y,
                hydro_inertia_z,
                inertia_coef_x,
                inertia_coef_y,
                inertia_coef_z,
                ]

    # Combine properties into disctionary
    hydrodynamic_properties = dict(zip(labels, values))

    return hydrodynamic_properties
        
def calc_hydro_properties_buoyancy_module(
    width   : float, 
    length  : float, 
    height  : float
    ):
    """
    Function: Calculates the hydrodynamic property of the buoyancy modules based on dimensions.
    
    Returns: dictionary of buoy hydro properties
    
    """
    # We interpolate sizes depending on the uplift force provided

    # Table B-2 Drag coefficient on three­dimensional objects for steady flow CDS 
    # Rectangular plate normal to flow direction
    b_to_h_plate_drag   = [1,5,10,10000]
    cds_plate           = [1.16,1.20,1.50,1.90]

    # Prism
    l_to_d_rod  = [1,1.5,2,2.5,3,4,5]
    Cds_rod     = [1.15,0.97,0.87,0.9,0.93,0.95,0.95]

    # Constants according to DNVGL-RP-N103 
    # Table A-2 Analytical added mass coefficient for three­dimensional bodies in infinite fluid
    b_to_a_flat = [1.000,1.250,1.500,1.590,2.000,2.500,3.000,3.170,4.000,5.000,6.250,8.000,10.000,1000]
    Ca_flat     = [0.579,0.642,0.690,0.704,0.757,0.801,0.830,0.840,0.872,0.897,0.917,0.934,0.947,1.000]  

    b_to_a_prism    = [1.0,2.0,3.0,4.0,5.0,6.0,7.0,10.0]  
    ca_prism        = [0.68,0.36,0.24,0.19,0.15,0.13,0.11,0.08]

    # Drag areas
    drag_area_x = height * length
    drag_area_y = height * width
    drag_area_z = length * width

    # Drag coefficients
    b_to_h_x        = height / length
    b_to_h_y        = height / width
    l_to_d_z_one    = height / length
    l_to_d_z_two    = height / width

    cds_x = np.interp(b_to_h_x, b_to_h_plate_drag, cds_plate)
    cds_y = np.interp(b_to_h_y, b_to_h_plate_drag, cds_plate)
    cds_z = max(np.interp(l_to_d_z_one, l_to_d_rod, Cds_rod), np.interp(l_to_d_z_two, l_to_d_rod, Cds_rod))

    # Added mass coefficients

    b_to_a_x = height / length
    b_to_a_y = height / width
    b_to_a_z_one = height / length
    b_to_a_z_two = height / width

    ca_x = np.interp(b_to_a_x, b_to_a_flat, Ca_flat)
    ca_y = np.interp(b_to_a_y, b_to_a_flat, Ca_flat)
    ca_z = max(np.interp(b_to_a_z_one, b_to_a_prism, ca_prism), np.interp(b_to_a_z_two, b_to_a_prism, ca_prism))

    buoy_hydro = {
        "dragAreaX" : drag_area_x,
        "dragAreaY" : drag_area_y,
        "dragAreaZ" : drag_area_z,
        "cdX" : cds_x,
        "cdY" : cds_y,
        "cdZ" : cds_z,
        "caX" : ca_x,
        "caY" : ca_y,
        "caZ" : ca_z
    }

    return buoy_hydro

def create_2ndEndStructure(
    model           : object, 
    line_dict       : dict, 
    plet_modelling  : str, 
    stage           : str
    ):
    '''
    Functions   :   Create the PLET structure inside the model
    
    Args        :   -model (the model in which to build the structure)
                    -line_dict (the job dict)
                    -plet_modelling (the PLET modelling selection ie frame only, with wings, no wings)
                    -stage (if mudmat wings used, the stage where the wings are deployed is stage 2. anything else is stage 1)
    
    Returns     :   plet_dict, mudmat_down_dict
    ''' 
        
    def _draw_structure(
        model   : object, 
        pletObj : object, 
        pletL   : float, 
        pletW   : float, 
        pletH   : float
        ):  
        
        a = [-0.5*pletL, -0.5*pletW, 0.5*pletH]
        b = [-0.5*pletL, 0.5*pletW,  0.5*pletH]
        c = [0.5*pletL,  0.5*pletW,  0.5*pletH]
        d = [0.5*pletL,  -0.5*pletW, 0.5*pletH]
        e = [-0.5*pletL, -0.5*pletW, -0.5*pletH]
        f = [-0.5*pletL, 0.5*pletW,  -0.5*pletH]
        g = [0.5*pletL,  0.5*pletW,  -0.5*pletH]
        h = [0.5*pletL,  -0.5*pletW, -0.5*pletH]
        
        pletObj.NumberofVertices   = 8
        pletObj.NumberofEdges      = 12
        
        pletObj.VertexX = [a[0], b[0], c[0], d[0], e[0], f[0], g[0], h[0]]
        pletObj.VertexY = [a[1], b[1], c[1], d[1], e[1], f[1], g[1], h[1]]
        pletObj.VertexZ = [a[2], b[2], c[2], d[2], e[2], f[2], g[2], h[2]]
        
        pletObj.EdgeFrom   = [1, 2, 3, 4, 5, 6, 7, 8, 1, 2, 3, 4]
        pletObj.EdgeTo     = [2, 3, 4, 1, 6, 7, 8, 5, 5, 6, 7, 8]
        
        return model
        
    def _assign_structure_hydro(
        model           : object, 
        pletObj         : object, 
        plet_dict       : dict, 
        pletL           : float, 
        pletW           : float, 
        pletH           : float, 
        has_seabedContact   : bool, 
        stage           : str
        ):
                
        # Frame Inertia
        pletObj.MassMomentOfInertiaX = plet_dict['mass_inertia_x']
        pletObj.MassMomentOfInertiaY = plet_dict['mass_inertia_y']
        pletObj.MassMomentOfInertiaZ = plet_dict['mass_inertia_z']
        # Frame Geometry
        pletObj.Volume               = plet_dict['volume']
        pletObj.Height               = pletH
        pletObj.CentreOfVolumeX      = 0
        pletObj.CentreOfVolumeY      = 0
        pletObj.CentreOfVolumeZ      = 0
        # Translation - Drag
        pletObj.DragAreaX              = plet_dict['drag_area_x']
        pletObj.DragAreaY              = plet_dict['drag_area_y']
        pletObj.DragAreaZ              = plet_dict['drag_area_z']
        if stage == "Stage_1":
            pletObj.DragForceCoefficientX  = plet_dict['cd_splashzone_x']
            pletObj.DragForceCoefficientY  = plet_dict['cd_splashzone_y']
            pletObj.DragForceCoefficientZ  = plet_dict['cd_splashzone_z']
        elif stage == "Stage_2":
            pletObj.DragForceCoefficientX  = plet_dict['cd_deep_x']
            pletObj.DragForceCoefficientY  = plet_dict['cd_deep_y']
            pletObj.DragForceCoefficientZ  = plet_dict['cd_deep_z']
        # Translation - Fluid Inertia
        pletObj.AddedMassCoefficientX  = plet_dict['ca_adjusted_x']
        pletObj.AddedMassCoefficientY  = plet_dict['ca_adjusted_y']
        pletObj.AddedMassCoefficientZ  = plet_dict['ca_adjusted_z']
        # Rotation - Drag Moment
        if stage == "Stage_1":
            pletObj.DragAreaMomentX        = plet_dict['drag_moment_area_splash_x']
            pletObj.DragAreaMomentY        = plet_dict['drag_moment_area_splash_y']
            pletObj.DragAreaMomentZ        = plet_dict['drag_moment_area_splash_z']
        elif stage == "Stage_2":
            pletObj.DragAreaMomentX        = plet_dict['drag_moment_area_deep_x']
            pletObj.DragAreaMomentY        = plet_dict['drag_moment_area_deep_y']
            pletObj.DragAreaMomentZ        = plet_dict['drag_moment_area_deep_z']
        pletObj.DragMomentCoefficientX = plet_dict['drag_mom_coef_x']
        pletObj.DragMomentCoefficientY = plet_dict['drag_mom_coef_y']
        pletObj.DragMomentCoefficientZ = plet_dict['drag_mom_coef_z']
        # Rotation - Fluid Inertia
        pletObj.HydrodynamicInertiaX   = plet_dict['hydro_inertia_x']
        pletObj.HydrodynamicInertiaY   = plet_dict['hydro_inertia_y']
        pletObj.HydrodynamicInertiaZ   = plet_dict['hydro_inertia_z']
        pletObj.AddedInertiaCoefficientX = plet_dict['inertia_coef_x']
        pletObj.AddedInertiaCoefficientY = plet_dict['inertia_coef_y']
        pletObj.AddedInertiaCoefficientZ = plet_dict['inertia_coef_z']
        # Contact
        pletObj.SeabedFrictionCoefficient = 0.3
        
        if has_seabedContact == True: 
            contactArea = pletL*pletW
        else:
            contactArea = 0
            
        pletObj.TotalContactArea          = contactArea
        
        return model
        
    ## If Frame Only: Frame_1 
    ## If Frame & Mudmat, no Wings: Frame_1 + Mudmat_1
    ## If Frame & Mudmat with Wings: Frame_1 + Mudmat_1 (Wing Down), Frame_2 (Wing Up)
    
    plet_identifier = "-"       
    #######################################################################
    if plet_modelling == "Frame only": 
        plet_identifier = "A"
               
    elif plet_modelling == "Frame & Mudmat (No Wings)":  
        plet_identifier = "A"
               
    elif plet_modelling == "Frame & Mudmat (With Wings)":               
        if stage == "Stage_2":
            # --- Regular separate mudmat/frame modelling (Stage 2)
            plet_identifier = "A"     
        else:
            # --- Integrated Mudmat/Frame Modelling (Stage 1)
            plet_identifier = "B"    
            
    #######################################################################     
    if plet_identifier == "A":     
        ## Create basic PLET frame at an initial position, anywhere (Frame_1)    
        plet_frame          = model.CreateObject(of.ot6DBuoy, 'PLET_Frame')
        plet_frame.BuoyType = 'Lumped Buoy'
        plet_frame.InitialX = 0
        plet_frame.InitialY = 0
        plet_frame.InitialZ = float(line_dict["General"].get("WD"))
        plet_frame.DegreesOfFreedomInStatics = "X,Y,Z"
        #
        plet_frame.Mass = float(line_dict["structureGeneral"].get("Frame_AirWeight"))    
        plet_frame.CentreOfMassX = float(line_dict["structureGeneral"].get("Frame_COG_X"))
        plet_frame.CentreOfMassY = float(line_dict["structureGeneral"].get("Frame_COG_Y"))
        plet_frame.CentreOfMassZ = float(line_dict["structureGeneral"].get("Frame_COG_Z"))
        #
        plet_frame_SW   = float(line_dict["structureGeneral"].get("Frame_SubWeight"))
        plet_perfor_X   = float(line_dict["structureGeneral"].get("Frame_Perfor_X"))
        plet_perfor_Y   = float(line_dict["structureGeneral"].get("Frame_Perfor_Y"))
        plet_perfor_Z   = float(line_dict["structureGeneral"].get("Frame_Perfor_Z"))
        #
        pletLength = float(line_dict["structureGeneral"].get("Frame_Length"))
        pletWidth  = float(line_dict["structureGeneral"].get("Frame_Width"))
        pletHeight = float(line_dict["structureGeneral"].get("Frame_Height"))

        model = _draw_structure(model, plet_frame, pletLength, pletWidth, pletHeight)

        ## Hydro Properties
        plet_dict = {}    
        plet_dict = calc_hydro_properties_rectangular_plate(
            pletLength, pletWidth, pletHeight,        
            plet_frame.Mass, plet_frame_SW,        
            plet_perfor_X, plet_perfor_Y, plet_perfor_Z,        
            constants.SEAWATER_DENSITY,
            plet_frame.CentreOfMassX, plet_frame.CentreOfMassY ,plet_frame.CentreOfMassZ        
        )

        has_seabedContact = True
        model = _assign_structure_hydro(model, plet_frame, plet_dict, pletLength, pletWidth, pletHeight, has_seabedContact, stage)
        
        # ------ Create Structure Marker 3D Buoy for Declination and Clearance ------- #
        
        marker_buoy               = model.CreateObject(of.ot6DBuoy, "PLET_Marker")
        marker_buoy.BuoyType      = "Lumped Buoy"
        marker_buoy.Connection    = "PLET_Frame"
        marker_buoy.InitialX      = -0.5*pletLength
        marker_buoy.InitialY      = 0.0
        marker_buoy.InitialZ      = -0.5*pletHeight

        marker_buoy.VertexX = [0.2, 0.0,  0.0,  0.2, 0.2, 0.0,  0.0,  0.2]
        marker_buoy.VertexY = [0.1, 0.1, -0.1, -0.1, 0.1, 0.1, -0.1, -0.1]
        marker_buoy.VertexZ = [0.2, 0.2,  0.2,  0.2, 0.0, 0.0,  0.0,  0.0]
        marker_buoy.EdgeFrom   = [1, 2, 3, 4, 5, 6, 7, 8, 1, 2, 3, 4]
        marker_buoy.EdgeTo     = [2, 3, 4, 1, 6, 7, 8, 5, 5, 6, 7, 8]

        marker_buoy.PenColour = 0xFFFF00
        
        marker_buoy.Mass = 0.0
        marker_buoy.MassMomentOfInertiaX = 0.0
        marker_buoy.MassMomentOfInertiaY = 0.0
        marker_buoy.MassMomentOfInertiaZ = 0.0
        
        marker_buoy.Volume = 0.0
        marker_buoy.Height = 1.0
        
        # --- Mudmat Properties placeholder
        mudmat_down_dict = {}
        
        #if (plet_modelling == "Frame & Mudmat (No Wings)"):
        if (plet_modelling != "Frame only"):
            
            # If Mudmat Wing Down or Mudmat Regular No Wing, both saved as Wing Down
            mudmat_down             = model.CreateObject(of.ot6DBuoy, "Mudmat")
            mudmat_down.BuoyType    = 'Lumped Buoy'            
            mudmat_down.Connection  = "PLET_Frame"
            #
            mudmat_down.Mass          = float(line_dict["structureGeneral"].get("Mudmat_AirWeight_WingDown"))       
            mudmat_down.CentreOfMassX = float(line_dict["structureGeneral"].get("Mudmat_COG_X_WingDown"))
            mudmat_down.CentreOfMassY = float(line_dict["structureGeneral"].get("Mudmat_COG_Y_WingDown"))
            mudmat_down.CentreOfMassZ = float(line_dict["structureGeneral"].get("Mudmat_COG_Z_WingDown"))
            #
            mudmat_SW              = float(line_dict["structureGeneral"].get("Mudmat_SubWeight_WingDown"))
            mudmat_down_perfor_X   = float(line_dict["structureGeneral"].get("Mudmat_Perfor_X_WingDown"))
            mudmat_down_perfor_Y   = float(line_dict["structureGeneral"].get("Mudmat_Perfor_Y_WingDown"))
            mudmat_down_perfor_Z   = float(line_dict["structureGeneral"].get("Mudmat_Perfor_Z_WingDown"))            
            #
            mudmatDownLength = float(line_dict["structureGeneral"].get("Mudmat_Length_WingDown"))
            mudmatDownWidth  = float(line_dict["structureGeneral"].get("Mudmat_Width_WingDown"))
            mudmatDownHeight = float(line_dict["structureGeneral"].get("Mudmat_Height_WingDown"))
            #
            mudmat_down.InitialX = float(line_dict["structureGeneral"].get("Mudmat_FrameConnX"))
            mudmat_down.InitialY = float(line_dict["structureGeneral"].get("Mudmat_FrameConnY"))
            mudmat_down.InitialZ = -0.5*pletHeight - 0.5*mudmatDownHeight
            #
            model = _draw_structure(model, mudmat_down, mudmatDownLength, mudmatDownWidth, mudmatDownHeight)
            
            ## Hydro Properties
            mudmat_down_dict = calc_hydro_properties_rectangular_plate(
                mudmatDownLength, mudmatDownWidth, mudmatDownHeight,        
                mudmat_down.Mass, mudmat_SW,        
                mudmat_down_perfor_X, mudmat_down_perfor_Y, mudmat_down_perfor_Z,        
                constants.SEAWATER_DENSITY,
                mudmat_down.CentreOfMassX, mudmat_down.CentreOfMassY , mudmat_down.CentreOfMassZ        
            )
            
            has_seabedContact = False
            model = _assign_structure_hydro(model, mudmat_down, mudmat_down_dict, mudmatDownLength, mudmatDownWidth, mudmatDownHeight, has_seabedContact, stage)
            
            # Change PLET Marker connection to Mudmat
            marker_buoy.Connection    = "Mudmat"
            marker_buoy.InitialX      = -0.5*mudmatDownLength
            marker_buoy.InitialY      = 0.0
            marker_buoy.InitialZ      = -0.5*mudmatDownHeight
                        
    elif plet_identifier == "B":
        
        #In this case, take new set of Data for INTEGRATED frame & mudmat for Mudmat Wing Up.
        
        #In this case, do a new Frame Only but take data from Mudmat Up.
        plet_frame          = model.CreateObject(of.ot6DBuoy, 'PLET_Frame')
        plet_frame.BuoyType = 'Lumped Buoy'
        plet_frame.InitialX = 0
        plet_frame.InitialY = 0
        plet_frame.InitialZ = float(line_dict["General"].get("WD"))
        plet_frame.DegreesOfFreedomInStatics = "X,Y,Z"
        #
        plet_frame.Mass = float(line_dict["structureGeneral"].get("Frame_AirWeight_WingUp"))    
        plet_frame.CentreOfMassX = float(line_dict["structureGeneral"].get("Frame_COG_X_WingUp"))
        plet_frame.CentreOfMassY = float(line_dict["structureGeneral"].get("Frame_COG_Y_WingUp"))
        plet_frame.CentreOfMassZ = float(line_dict["structureGeneral"].get("Frame_COG_Z_WingUp"))
        #
        plet_frame_SW   = float(line_dict["structureGeneral"].get("Frame_SubWeight_WingUp"))
        plet_perfor_X   = float(line_dict["structureGeneral"].get("Frame_Perfor_X_WingUp"))
        plet_perfor_Y   = float(line_dict["structureGeneral"].get("Frame_Perfor_Y_WingUp"))
        plet_perfor_Z   = float(line_dict["structureGeneral"].get("Frame_Perfor_Z_WingUp"))
        #
        pletLength = float(line_dict["structureGeneral"].get("Frame_Length_WingUp"))
        pletWidth  = float(line_dict["structureGeneral"].get("Frame_Width_WingUp"))
        pletHeight = float(line_dict["structureGeneral"].get("Frame_Height_WingUp"))
        #
        model = _draw_structure(model, plet_frame, pletLength, pletWidth, pletHeight)
        
        ## Hydro Properties
        plet_dict = {}    
        plet_dict = calc_hydro_properties_rectangular_plate(
            pletLength, pletWidth, pletHeight,        
            plet_frame.Mass, plet_frame_SW,        
            plet_perfor_X, plet_perfor_Y, plet_perfor_Z,        
            constants.SEAWATER_DENSITY,
            plet_frame.CentreOfMassX, plet_frame.CentreOfMassY, plet_frame.CentreOfMassZ        
        )
        
        has_seabedContact = True
        model = _assign_structure_hydro(model, plet_frame, plet_dict, pletLength, pletWidth, pletHeight, has_seabedContact, stage)
        
        # ------ Create Structure Marker 3D Buoy for Declination and Clearance ------- #
        
        marker_buoy               = model.CreateObject(of.ot6DBuoy, "PLET_Marker")
        marker_buoy.BuoyType      = "Lumped Buoy"
        marker_buoy.Connection    = "PLET_Frame"
        marker_buoy.InitialX      = -0.5*pletLength
        marker_buoy.InitialY      = 0.0
        marker_buoy.InitialZ      = -0.5*pletHeight

        marker_buoy.VertexX = [0.2, 0.0,  0.0,  0.2, 0.2, 0.0,  0.0,  0.2]
        marker_buoy.VertexY = [0.1, 0.1, -0.1, -0.1, 0.1, 0.1, -0.1, -0.1]
        marker_buoy.VertexZ = [0.2, 0.2,  0.2,  0.2, 0.0, 0.0,  0.0,  0.0]
        marker_buoy.EdgeFrom   = [1, 2, 3, 4, 5, 6, 7, 8, 1, 2, 3, 4]
        marker_buoy.EdgeTo     = [2, 3, 4, 1, 6, 7, 8, 5, 5, 6, 7, 8]

        marker_buoy.PenColour = 0xFFFF00
        
        marker_buoy.Mass = 0.0
        marker_buoy.MassMomentOfInertiaX = 0.0
        marker_buoy.MassMomentOfInertiaY = 0.0
        marker_buoy.MassMomentOfInertiaZ = 0.0
        
        marker_buoy.Volume = 0.0
        marker_buoy.Height = 1.0
        
        # No Mudmat, just placeholder       
        mudmat_down_dict = {}
               
    return plet_dict, mudmat_down_dict

def create_ARLinetype(
    model       : object, 
    wireline    : object,
    wireline2   : object, 
    wireline3   : object,
    line_dict   : dict,
    vessel_json : json
):
    '''
    Functions   :   Create the AR linetype
    
    Args        :   -model (the model in question)
                    -wireline (the main wire)
                    -wireline2 (the 2nd wire, in case dual mode)
                    -wireline3 (the 3rd wire, in case dual mode)
                    -line_dict (the job dict)
                    -vessel_json (the vessel dict)
    
    Returns     : -
    '''
    # ---- Get vessel type to determine what the A&R wires are called ---- #
    # (Simple CLI: fall back to the known line type names if the vessel JSON lacks the key)
    ARwire_Name = vessel_json.get("A&R Wire ID") or constants.AR_WIRE_IDS[vessel_json["Name"]]
    
    # Get Wire Attachment Location
    AR_mode    = line_dict["vesselGeneral"].get("AR_Mode")
    AR_hangoff = line_dict["vesselGeneral"].get("AR_Hangoff")
    AR_EndA    = line_dict["vesselGeneral"].get("VesselRamp")
    
    if AR_mode == "Single Mode":
        
        # Create AnR wire
        wireline.LineType[0]      = ARwire_Name 
        wireline.NumberOfSections = 2
        wireline.Length[0]        = 20
        wireline.Length[1]        = 35
        #
        wireline.TargetSegmentLength[0]    = 1
        wireline.TargetSegmentLength[1]    = 2    
        wireline.EndAConnection            = AR_EndA   

        #if AR_mode == "Single Mode": #AR_mode = vessel_json.get(line_dict["vesselGeneral"].get("AR_Mode"))
        wireline.EndAX = vessel_json["A&R Sheaves"][AR_hangoff][0]
        wireline.EndAY = vessel_json["A&R Sheaves"][AR_hangoff][1]
        wireline.EndAZ = vessel_json["A&R Sheaves"][AR_hangoff][2]

        wireline.Length[1]        = abs(wireline.EndAX)

        wireline.EndAAzimuth        = 180.0
        wireline.EndADeclination    = 90.0
        wireline.EndAGamma          = 0.0
        #
        wireline.EndBAzimuth        = 180.0
        wireline.EndBDeclination    = 90.0
        wireline.EndBGamma          = 0.0
        wireline.StaticsSeabedFrictionPolicy = "None"
        
    elif str(AR_mode).startswith("Dual Mode"):   # GUI value is "Dual Mode (A&R Beam)"

        # Open the model with the AR Beam
        ar_beam_location    = os.path.join(constants.VESSEL_DB_DIR, "vega")
        beam_model          = of.Model(os.path.join(ar_beam_location, "_vegaARbeam_1.0.dat"))
        beam_obj            = beam_model["A&R spreader beam"]
        
        clone               = beam_obj.CreateClone(model = model)         
        AR_Beam             = model["A&R spreader beam"]
        
        # -------- Create AnR wire 1 - Port Side to Beam
        wireline.LineType[0]      = ARwire_Name
        wireline.NumberOfSections = 2
        wireline.Length[0]        = 20
        wireline.Length[1]        = 35
        #
        wireline.TargetSegmentLength[0]    = 1
        wireline.TargetSegmentLength[1]    = 1    
        wireline.EndAConnection            = AR_EndA
        wireline.EndBConnection            = "A&R spreader beam"
        #
        wireline.EndAX = vessel_json["A&R Dual Mode"]["Port Sheave"][0]
        wireline.EndAY = vessel_json["A&R Dual Mode"]["Port Sheave"][1]
        wireline.EndAZ = vessel_json["A&R Dual Mode"]["Port Sheave"][2]
        #
        wireline.EndBX = 0.0
        wireline.EndBY = 4.3
        wireline.EndBZ = 0.0       
        #
        wireline.Length[1]          = abs(wireline.EndAX)
        wireline.EndAAzimuth        = 180.0
        wireline.EndADeclination    = 90.0
        wireline.EndAGamma          = 0.0
        #
        wireline.EndBAzimuth        = 180.0
        wireline.EndBDeclination    = 180.0
        wireline.EndBGamma          = 0.0
        wireline.StaticsSeabedFrictionPolicy = "None"
        
        # -------- Create AnR wire 2 - Starboard Side to Beam
        wireline2.LineType[0]      = ARwire_Name  
        wireline2.NumberOfSections = 2
        wireline2.Length[0]        = 20
        wireline2.Length[1]        = 35
        #
        wireline2.TargetSegmentLength[0]    = 1
        wireline2.TargetSegmentLength[1]    = 1    
        wireline2.EndAConnection            = AR_EndA
        wireline2.EndBConnection            = "A&R spreader beam"
        #
        wireline2.EndAX = vessel_json["A&R Dual Mode"]["Starboard Sheave"][0]
        wireline2.EndAY = vessel_json["A&R Dual Mode"]["Starboard Sheave"][1]
        wireline2.EndAZ = vessel_json["A&R Dual Mode"]["Starboard Sheave"][2]
        #
        wireline2.EndBX = 0.0
        wireline2.EndBY = -4.3
        wireline2.EndBZ = 0.0
        #
        wireline2.Length[1]          = abs(wireline2.EndAX)
        wireline2.EndAAzimuth        = 180.0
        wireline2.EndADeclination    = 90.0
        wireline2.EndAGamma          = 0.0
        #
        wireline2.EndBAzimuth        = 180.0
        wireline2.EndBDeclination    = 180.0
        wireline2.EndBGamma          = 0.0
        wireline2.StaticsSeabedFrictionPolicy = "None"
        
        # Create AnR wire 3 - Beam to PLET
        wireline3.LineType[0]      = ARwire_Name
        wireline3.NumberOfSections = 1
        wireline3.Length[0]        = float(line_dict["vesselGeneral"].get("BeamRigLength"))
        #
        wireline3.TargetSegmentLength[0]    = 1  
        wireline3.EndAConnection            = "A&R spreader beam"
        #
        wireline3.EndAX = 0.0
        wireline3.EndAY = 0.0
        wireline3.EndAZ = -0.8
        #
        wireline3.EndAAzimuth        = 180.0
        wireline3.EndADeclination    = 180.0
        wireline3.EndAGamma          = 0.0
        #
        wireline3.EndBAzimuth        = 180.0
        wireline3.EndBDeclination    = 90.0
        wireline3.EndBGamma          = 0.0
        wireline3.StaticsSeabedFrictionPolicy = "None"
        
        # Move AR Beam to a more suitable starting location later
        AR_Beam.InitialX = -25.0
        AR_Beam.InitialZ = 10.0
                     
def create_ARConnection(
    model       : object, 
    wireline    : object,
    wireline3   : object,
    line_dict   : dict, 
    stage       : str
):
    '''
    Functions   :   Create the AR connection for the model
    
    Args        :   -model (the model in which to build the structure)
                    -wireline (the ar wire)
                    -wireline3 (the ar wire, if dual mode used)
                    -line_dict (the job dict)
                    -stage (if mudmat wings used, the stage where the wings are deployed is stage 2. anything else is stage 1)
    
    Returns     :   -
    '''
    # Get AnR Wire attachment type to PLET
    AR_PLET_attach = line_dict["structureGeneral"].get("AR_Type")
    AR_Mode        = line_dict["vesselGeneral"].get("AR_Mode")
    
    # Create General 6D Buoy to Attach Wire to Padeye or Yoke
    PLET_WireAttach = model.CreateObject(of.ot6DBuoy, "PLET_WireAttach")
    PLET_WireAttach.Mass = 0.001
    PLET_WireAttach.MassMomentOfInertiaX = 0
    PLET_WireAttach.MassMomentOfInertiaY = 0
    PLET_WireAttach.MassMomentOfInertiaZ = 0
    PLET_WireAttach.Volume = 0.0
    PLET_WireAttach.Height = 0.2
    dummySz = 0.1
    PLET_WireAttach.VertexX = [dummySz, -dummySz, -dummySz, dummySz, dummySz, -dummySz, -dummySz, dummySz]
    PLET_WireAttach.VertexY = [dummySz, dummySz, -dummySz, -dummySz, dummySz, dummySz, -dummySz, -dummySz]
    PLET_WireAttach.VertexZ = [dummySz, dummySz, dummySz, dummySz, -dummySz, -dummySz, -dummySz, -dummySz]
    PLET_WireAttach.PenColour = 0xFF5733
    #
    if AR_Mode == "Single Mode":
        wireline.EndBConnection                        = "PLET_WireAttach"
        wireline.EndBX, wireline.EndBY, wireline.EndBZ = [0, 0, 0]
    else:
        wireline3.EndBConnection                          = "PLET_WireAttach"
        wireline3.EndBX, wireline3.EndBY, wireline3.EndBZ = [0, 0, 0]
    
    plet_model = line_dict["structureGeneral"].get('PLETModellingOpt')
    
    if AR_PLET_attach == "Single Padeye":
        
        PLET_WireAttach.Connection = "PLET_Frame"
        
        if plet_model != "Frame & Mudmat (With Wings)" or stage == "Stage_2":
            PLET_WireAttach.InitialX   = line_dict["structureGeneral"].get("AR_XCoor")
            PLET_WireAttach.InitialY   = 0.0 ##line_dict["structureGeneral"].get("AR_YCoor")
            PLET_WireAttach.InitialZ   = line_dict["structureGeneral"].get("AR_ZCoor")
            
        if plet_model == "Frame & Mudmat (With Wings)" and stage == "Stage_1":
            PLET_WireAttach.InitialX   = line_dict["structureGeneral"].get("AR_XCoor_WingUp")
            PLET_WireAttach.InitialY   = 0.0 ##line_dict["structureGeneral"].get("AR_YCoor_WingUp")
            PLET_WireAttach.InitialZ   = line_dict["structureGeneral"].get("AR_ZCoor_WingUp")
                                                                                   
    elif AR_PLET_attach == "Yoke":
        
        ##yoke_linetype        = model.CreateObject(of.otLineType, "ARYoke")
        ##yoke_linetype.OD     = 0.001
        ##yoke_linetype.ID     = 0.0
        # Get Total Length of Yoke Modelled to Calc Unit Mass
        AR_Length       = float(line_dict["structureGeneral"].get("AR_Length"))
        AR_Width        = float(line_dict["structureGeneral"].get("AR_Width"))
        ARYoke_Weight   = float(line_dict["structureGeneral"].get("AR_AirWeight"))
        yoke_len        = 2*AR_Length + AR_Width
        yoke_unitmass   = ARYoke_Weight/yoke_len
        #
        ##yoke_linetype.MassPerUnitLength      = yoke_unitmass 
        ##yoke_linetype.EIx, yoke_linetype.EIy = [30e3, 30e3] 
        ##yoke_linetype.EA                     = 300e3
        ##yoke_linetype.PoissonRatio           = 0.3
        ##yoke_linetype.GJ                     = 40e3
        ##yoke_linetype.Cdx, yoke_linetype.Cdy = [2.0, 2.0]        
        ##yoke_linetype.Cdz                    = 0.008
        ##yoke_linetype.PenColour              = 0xFF5733
        #
        # ---------------- Create Yoke Constraint  ---------------- #
        ARYoke_RotStiffness = model.CreateObject(of.otConstraintRotationalStiffness, "AR_Yoke_RotStiffness")
        # Pull the yoke stiffness table
        ARYokeStiffdict = line_dict["structureGeneral"].get("AR_YokeStiffnessTable")
        angular_disp      = []
        moment            = []
        for item in ARYokeStiffdict:
            angle = item.get("AngularDisplacement")
            angular_disp.append(angle)
            mom   = item.get("Moment")
            moment.append(mom)  
        ARYoke_RotStiffness.IndependentValue = angular_disp
        ARYoke_RotStiffness.DependentValue   = moment
        #
        ARYoke_constraint   = model.CreateObject(of.otConstraint, "AR_Yoke_Hinge")
        ARYoke_constraint.DOFFree[4]             = "Yes"
        ARYoke_constraint.TranslationalStiffness = 0
        ARYoke_constraint.RotationalStiffness    = "AR_Yoke_RotStiffness"
        ARYoke_constraint.Connection             = "PLET_Frame"
        #
        AR_conn_x = float(line_dict["structureGeneral"].get("AR_XCoor"))
        AR_conn_y = abs(float(line_dict["structureGeneral"].get("AR_YCoor")))
        AR_conn_z = float(line_dict["structureGeneral"].get("AR_ZCoor"))
        ARwu_conn_x = float(line_dict["structureGeneral"].get("AR_XCoor_WingUp"))
        ARwu_conn_y = abs(float(line_dict["structureGeneral"].get("AR_YCoor_WingUp")))
        ARwu_conn_z = float(line_dict["structureGeneral"].get("AR_ZCoor_WingUp"))
        
        if plet_model != "Frame & Mudmat (With Wings)" or stage == "Stage_2":
            ARYoke_constraint.InitialX               = AR_conn_x
            ARYoke_constraint.InitialY               = -1*AR_conn_y
            ARYoke_constraint.InitialZ               = AR_conn_z
            
        if plet_model == "Frame & Mudmat (With Wings)" and stage == "Stage_1":
            ARYoke_constraint.InitialX               = ARwu_conn_x
            ARYoke_constraint.InitialY               = -1*ARwu_conn_y
            ARYoke_constraint.InitialZ               = ARwu_conn_z
        ARYoke_constraint.InitialDeclination     = 0.0
        
        # Create the Towed Fish Yoke
        # Top (Middle) Part
        ARYoke_3              = model.CreateObject(of.ot6DBuoy, "ARYoke_3")
        ARYoke_3.BuoyType     = "Towed fish"
        ARYoke_3.Connection   = "AR_Yoke_Hinge"
        ARYoke_3.InitialX     = float(line_dict["structureGeneral"].get("AR_Length")) 
        ARYoke_3.InitialY             = 0.0
        ARYoke_3.InitialZ             = 0.0
        ARYoke_3.InitialRotation2     = 90.0
        ARYoke_3.InitialRotation3     = 90.0
        ARYoke_3.Mass                 = 0.001
        ARYoke_3.MassMomentOfInertiaX = 0.0
        ARYoke_3.MassMomentOfInertiaY = 0.0
        ARYoke_3.MassMomentOfInertiaZ = 0.0
        ARYoke_3.CylinderOuterDiameter[0] = 0.27305
        ARYoke_3.CylinderInnerDiameter[0] = 0.23658
        ARYoke_3.CylinderLength[0]        = float(line_dict["structureGeneral"].get("AR_Width"))
        ARYoke_3.NormalDragAreaCalculatedFromGeometry     = "Yes"
        ARYoke_3.CylinderNormalDragForceCoefficient[0]    = 1.2
        ARYoke_3.DampingRelativeTo                        = "Fluid"
        ARYoke_3.CylinderNormalAddedMassForceCoefficient[0] = 1.2
        ARYoke_3.CylinderAxialAddedMassForceCoefficient[0]  = 1.0
        # Right Leg
        ARYoke_1              = model.CreateObject(of.ot6DBuoy, "ARYoke_1")
        ARYoke_1.BuoyType     = "Towed fish"
        ARYoke_1.Connection   = "ARYoke_3"
        ARYoke_1.InitialX             = 0.0
        ARYoke_1.InitialY             = 0.0
        ARYoke_1.InitialZ             = -1*float(line_dict["structureGeneral"].get("AR_Length")) 
        ARYoke_1.InitialRotation1     = -90.0
        ARYoke_1.InitialRotation2     = 0.0
        ARYoke_1.InitialRotation3     = -90.0
        ARYoke_1.Mass                 = 0.001
        ARYoke_1.MassMomentOfInertiaX = 0.0
        ARYoke_1.MassMomentOfInertiaY = 0.0
        ARYoke_1.MassMomentOfInertiaZ = 0.0
        ARYoke_1.CylinderOuterDiameter[0] = 0.27305
        ARYoke_1.CylinderInnerDiameter[0] = 0.23658
        ARYoke_1.CylinderLength[0]        = float(line_dict["structureGeneral"].get("AR_Length")) 
        ARYoke_1.NormalDragAreaCalculatedFromGeometry     = "Yes"
        ARYoke_1.CylinderNormalDragForceCoefficient[0]    = 1.2
        ARYoke_1.DampingRelativeTo                        = "Fluid"
        ARYoke_1.CylinderNormalAddedMassForceCoefficient[0] = 1.2
        ARYoke_1.CylinderAxialAddedMassForceCoefficient[0]  = 1.0
        # Left Leg
        ARYoke_2              = model.CreateObject(of.ot6DBuoy, "ARYoke_2")
        ARYoke_2.BuoyType     = "Towed fish"
        ARYoke_2.Connection   = "ARYoke_3"
        ARYoke_2.InitialX             = float(line_dict["structureGeneral"].get("AR_Width")) 
        ARYoke_2.InitialY             = 0.0
        ARYoke_2.InitialZ             = -1*float(line_dict["structureGeneral"].get("AR_Length")) 
        ARYoke_2.InitialRotation1     = -90.0
        ARYoke_2.InitialRotation2     = 0.0
        ARYoke_2.InitialRotation3     = -90.0
        ARYoke_2.Mass                 = 0.001
        ARYoke_2.MassMomentOfInertiaX = 0.0
        ARYoke_2.MassMomentOfInertiaY = 0.0
        ARYoke_2.MassMomentOfInertiaZ = 0.0
        ARYoke_2.CylinderOuterDiameter[0] = 0.27305
        ARYoke_2.CylinderInnerDiameter[0] = 0.23658
        ARYoke_2.CylinderLength[0]        = float(line_dict["structureGeneral"].get("AR_Length")) 
        ARYoke_2.NormalDragAreaCalculatedFromGeometry     = "Yes"
        ARYoke_2.CylinderNormalDragForceCoefficient[0]    = 1.2
        ARYoke_2.DampingRelativeTo                        = "Fluid"
        ARYoke_2.CylinderNormalAddedMassForceCoefficient[0] = 1.2
        ARYoke_2.CylinderAxialAddedMassForceCoefficient[0]  = 1.0
        # Create Buoy Yoke COG Item
        ARyoke_COG        = model.CreateObject(of.ot6DBuoy, "ARYokeCOG")
        ARyoke_COG.Mass   = ARYoke_Weight
        ARyoke_COG.MassMomentOfInertiaX = 0
        ARyoke_COG.MassMomentOfInertiaY = 0
        ARyoke_COG.MassMomentOfInertiaZ = 0
        ARyoke_COG.Volume     = 0.1
        ARyoke_COG.Height     = 0.1
        ARyoke_COG.Connection = "AR_Yoke_Hinge"
        ARyoke_COG.InitialX   = float(line_dict["structureGeneral"].get("ARYoke_COG")) 
        ARyoke_COG.InitialY   = 0.5*float(line_dict["structureGeneral"].get("AR_Width"))
        ARyoke_COG.InitialZ   = 0
        ARyoke_COG.InitialRotation1 = 0.0
        ARyoke_COG.InitialRotation2 = 0.0
        ARyoke_COG.InitialRotation3 = 0.0
        ARyoke_COG.PenColour  = 0xFF69B4 # hot pink
        dummySz = 0.1
        ARyoke_COG.VertexX = [dummySz, -dummySz, -dummySz, dummySz, dummySz, -dummySz, -dummySz, dummySz]
        ARyoke_COG.VertexY = [dummySz, dummySz, -dummySz, -dummySz, dummySz, dummySz, -dummySz, -dummySz]
        ARyoke_COG.VertexZ = [dummySz, dummySz, dummySz, dummySz, -dummySz, -dummySz, -dummySz, -dummySz]
        
        # Place the attachment
        PLET_WireAttach.Connection = "AR_Yoke_Hinge"
        PLET_WireAttach.InitialX   = float(line_dict["structureGeneral"].get("AR_Length"))
        PLET_WireAttach.InitialY   = float(line_dict["structureGeneral"].get("AR_Width"))*0.5
        PLET_WireAttach.InitialZ   = 0.0
        PLET_WireAttach.InitialRotation1 = 0
        PLET_WireAttach.InitialRotation2 = 0
        PLET_WireAttach.InitialRotation3 = -90
                        
        # ---------------- Create Yoke Item --------------------- #
        ##ARYoke_IDs = [
        ##    constants.ANR_YOKE_NAME + "_par1",
        ##    constants.ANR_YOKE_NAME + "_par2",
        ##    constants.ANR_YOKE_NAME + "_par3"
        ##]
        ##
        ##ARYoke_1 = model.CreateObject(of.otLine, ARYoke_IDs[0])
        ##ARYoke_2 = model.CreateObject(of.otLine, ARYoke_IDs[1])
        ##ARYoke_3 = model.CreateObject(of.otLine, ARYoke_IDs[2]) 
        ###
        ##set_ARYoke = [ARYoke_1, ARYoke_2, ARYoke_3]   
        ##for yokeObj in set_ARYoke:
        ##    yokeObj.LineType[0]     = "ARYoke"
        ##    yokeObj.EndAConnection  = "AR_Yoke_Hinge"
        ##    yokeObj.EndBConnection  = "AR_Yoke_Hinge"
        ##    yokeObj.StaticsSeabedFrictionPolicy = 'None'
        ##    yokeObj.EndAxBendingStiffness       = 0
        ##    yokeObj.EndBxBendingStiffness       = 0
        ##    yokeObj.EndADeclination             = 90
        ##    yokeObj.EndBDeclination             = 90
        ##    yokeObj.NodePenColour = 0XFF5733
        ### 
        ##ARYoke_1.Length[0], ARYoke_2.Length[0]                           = [AR_Length, AR_Length] 
        ##ARYoke_3.Length[0], ARYoke_3.TargetSegmentLength[0]              = [AR_Width, AR_Width]
        ##ARYoke_1.TargetSegmentLength[0], ARYoke_2.TargetSegmentLength[0] = [AR_Length, AR_Length]
        ### 
        ### --- AR Yoke Connection Point on Frame 
        ##AR_con = float(line_dict["structureGeneral"].get("AR_YCoor"))
        ##
        ##ARYoke_1.EndAX, ARYoke_1.EndAY, ARYoke_1.EndAZ      = [  0,       -AR_con, 0]
        ##ARYoke_1.EndBX, ARYoke_1.EndBY, ARYoke_1.EndBZ      = [AR_Length, -AR_con, 0]
        ##ARYoke_1.EndAAzimuth, ARYoke_1.EndBAzimuth          = [180, 180]
        ##ARYoke_1.EndADeclination, ARYoke_1.EndBDeclination  = [90, 90]
        ##ARYoke_1.EndAGamma, ARYoke_1.EndBGamma              = [180, 180]
        ###
        ##ARYoke_2.EndAX, ARYoke_2.EndAY, ARYoke_2.EndAZ   = [        0, AR_con, 0]
        ##ARYoke_2.EndBX, ARYoke_2.EndBY, ARYoke_2.EndBZ   = [AR_Length, AR_con, 0]
        ##ARYoke_2.EndAAzimuth, ARYoke_2.EndBAzimuth          = [180, 180]
        ##ARYoke_2.EndADeclination, ARYoke_2.EndBDeclination  = [90, 90]
        ##ARYoke_2.EndAGamma, ARYoke_2.EndBGamma              = [180, 180]
        ###
        ##ARYoke_3.EndAX, ARYoke_3.EndAY, ARYoke_3.EndAZ   = [AR_Length, -AR_con, 0]
        ##ARYoke_3.EndBX, ARYoke_3.EndBY, ARYoke_3.EndBZ   = [AR_Length,  AR_con, 0]
        ##ARYoke_3.EndAAzimuth, ARYoke_3.EndBAzimuth          = [90, 90]
        ##ARYoke_3.EndADeclination, ARYoke_3.EndBDeclination  = [90, 90]
        ##ARYoke_3.EndAGamma, ARYoke_3.EndBGamma              = [0, 0]
        
        # -------------------- #
        ##PLET_WireAttach.Connection = "AR_Yoke_Hinge"
        ##PLET_WireAttach.InitialX   = float(line_dict["structureGeneral"].get("AR_Length"))
        ##PLET_WireAttach.InitialY   = 0.0 #float(line_dict["structureGeneral"].get("AR_Width"))*0.5
        ##PLET_WireAttach.InitialZ   = 0.0
        ##PLET_WireAttach.InitialRotation1 = 0
        ##PLET_WireAttach.InitialRotation2 = 0
        ##PLET_WireAttach.InitialRotation3 = 0
    
def create_BuoyConnection(
    model       : object, 
    line_dict   : dict,
    stage       : str
):  
    '''
    Functions   :   Create the Buoy connection for the model
    
    Args        :   -model (the model in which to build the structure)
                    -line_dict (the job dict)
                    -stage (if mudmat wings used, the stage where the wings are deployed is stage 2. anything else is stage 1)
    
    Returns     :   -
    '''
    # Generally Used Items
    plet_frame = model["PLET_Frame"]
    
    # Get Type of Frame Modelled
    plet_model = line_dict["structureGeneral"].get("PLETModellingOpt") # opt: 'Frame only', 'Frame & Mudmat (No Wings)', 'Frame & Mudmat (With Wings)'
    if plet_model != "Frame & Mudmat (With Wings)" or stage == "Stage_2":
        conn_x = line_dict["buoyGeneral"].get("Connection_X")
        conn_y = abs(line_dict["buoyGeneral"].get("Connection_Y"))
        conn_z = line_dict["buoyGeneral"].get("Connection_Z")
    if plet_model == "Frame & Mudmat (With Wings)" and stage == "Stage_1":
        conn_x = line_dict["buoyGeneral"].get("Connection_X_WingUp")
        conn_y = abs(line_dict["buoyGeneral"].get("Connection_Y_WingUp"))
        conn_z = line_dict["buoyGeneral"].get("Connection_Z_WingUp")
            
    # Get Buoy attachment type to PLET
    useBuoy = line_dict["buoyGeneral"].get("UseBuoyancy")   
     
    if useBuoy == True:
        
        # Lower the PLET by appropriate amount
        buoydict = line_dict["buoyGeneral"].get("BuoyTable")
        sling_lengths = []
        for item in buoydict:
            len = item.get("SlingLength")
            sling_lengths.append(len)
            lenb = item.get("BuoyLength")
            sling_lengths.append(lenb)  
        linkyoke_len = line_dict["buoyGeneral"].get("LinkYokeLength")       
        totalBuoyLen = linkyoke_len + sum(sling_lengths)
        minBuoyWD    = totalBuoyLen + 30
        plet_frame.InitialZ = -1*minBuoyWD
                                            
        Buoy_PLET_attach = line_dict["buoyGeneral"].get("ConnectionType")   
         
        if Buoy_PLET_attach == "Running Wire":
            
            # Create Triplate
            BuoyTriplate            = model.CreateObject(of.ot3DBuoy, "Triplate")
            try:
                BuoyTriplate.IncludedInStatics = "No"
            except:
                pass
            BuoyTriplate.Connection = "Free"
            BuoyTriplate.Mass       = 0.01
            BuoyTriplate.Volume     = 0.001
            BuoyTriplate.Height     = 0.2
            BuoyTriplate.InitialZ   = -10 #plet_frame.InitialZ + linkyoke_len
            BuoyTriplate.InitialX   = plet_frame.InitialX - 2
            BuoyTriplate.InitialY   = plet_frame.InitialY
            
            # Create Slings/Bridle
            Sling_1 = model.CreateObject(of.otLink, "BuoySling_1")
            Sling_2 = model.CreateObject(of.otLink, "BuoySling_2")
            sling_obj = [Sling_1, Sling_2]
            ct = 0
            for obj in sling_obj:
                obj.LinkType            = "Tether"
                obj.UnstretchedLength   = line_dict["buoyGeneral"].get("LinkYokeLength")
                obj.Stiffness           = 100e3
                obj.EndAConnection      = "PLET_Frame"
                obj.EndAX               = conn_x
                if ct == 0:
                    obj.EndAY           = -1*conn_y     # this needs to be negative
                else:
                    obj.EndAY           = 1*conn_y  # this needs to be positive
                obj.EndAZ               = conn_z
                #
                obj.EndBConnection      = "Triplate"
                obj.EndBX, obj.EndBY, obj.EndBZ = [0, 0, 0]
                #
                h = np.sqrt(obj.UnstretchedLength**2 - line_dict["structureGeneral"].get("Frame_Width")**2)
                BuoyTriplate.InitialZ   = -10 #h + plet_frame.InitialZ + 2*line_dict["buoyGeneral"].get("Connection_X") 
                #
                ct += 1
        
        elif Buoy_PLET_attach == "Yoke":
            # Create 6d Buoy to Attach to Yoke
            PLET_BuoyAttach = model.CreateObject(of.ot6DBuoy, "PLET_BuoyAttach")
            PLET_BuoyAttach.Mass = 0.001
            PLET_BuoyAttach.MassMomentOfInertiaX = 0
            PLET_BuoyAttach.MassMomentOfInertiaY = 0
            PLET_BuoyAttach.MassMomentOfInertiaZ = 0
            PLET_BuoyAttach.Volume = 0.0
            PLET_BuoyAttach.Height = 0.2
            dummySz = 0.1
            PLET_BuoyAttach.VertexX = [dummySz, -dummySz, -dummySz, dummySz, dummySz, -dummySz, -dummySz, dummySz]
            PLET_BuoyAttach.VertexY = [dummySz, dummySz, -dummySz, -dummySz, dummySz, dummySz, -dummySz, -dummySz]
            PLET_BuoyAttach.VertexZ = [dummySz, dummySz, dummySz, dummySz, -dummySz, -dummySz, -dummySz, -dummySz]
            PLET_BuoyAttach.PenColour = 0x088F8F
            # Create Buoy Yoke Linetype
            ###Buoyyoke_linetype        = model.CreateObject(of.otLineType, "BuoyYoke")
            ###Buoyyoke_linetype.OD     = 0.001
            ###Buoyyoke_linetype.ID     = 0.0
            
            # Yoke Properties
            BuoyYoke_Weight   = float(line_dict["buoyGeneral"].get("YokeAirWeight"))
            BuoyYoke_Length   = float(line_dict["buoyGeneral"].get("LinkYokeLength"))
            
            # Create Yoke Constraints
            Buoyyoke_RotStiffness = model.CreateObject(of.otConstraintRotationalStiffness, "Buoy_Yoke_RotStiffness")
            # Pull the yoke stiffness table
            buoyYokeStiffdict = line_dict["buoyGeneral"].get("BuoyYokeStiffnessTable")
            angular_disp      = []
            moment            = []
            for item in buoyYokeStiffdict:
                angle = item.get("AngularDisplacement")
                angular_disp.append(angle)
                mom   = item.get("Moment")
                moment.append(mom)  
            Buoyyoke_RotStiffness.IndependentValue = angular_disp
            Buoyyoke_RotStiffness.DependentValue   = moment
            #
            Buoyyoke_constraint   = model.CreateObject(of.otConstraint, "Buoy_Yoke_Hinge")
            Buoyyoke_constraint.DOFFree[4]             = "Yes"
            Buoyyoke_constraint.TranslationalStiffness = 0
            Buoyyoke_constraint.RotationalStiffness    = "Buoy_Yoke_RotStiffness"
            Buoyyoke_constraint.Connection             = "PLET_Frame"
            Buoyyoke_constraint.InitialX               = conn_x
            Buoyyoke_constraint.InitialY               = -1*conn_y   # 0.0
            Buoyyoke_constraint.InitialZ               = conn_z
            Buoyyoke_constraint.InitialDeclination     = 0.0
            #
            # Create the Towed Fish Yoke
            # Top (Middle) Part
            BuoyYoke_3              = model.CreateObject(of.ot6DBuoy, "BuoyYoke_3")
            BuoyYoke_3.BuoyType     = "Towed fish"
            BuoyYoke_3.Connection   = "Buoy_Yoke_Hinge"
            BuoyYoke_3.InitialX     = BuoyYoke_Length
            BuoyYoke_3.InitialY             = 0.0
            BuoyYoke_3.InitialZ             = 0.0
            BuoyYoke_3.InitialRotation2     = 90.0
            BuoyYoke_3.InitialRotation3     = 90.0
            BuoyYoke_3.Mass                 = 0.001
            BuoyYoke_3.MassMomentOfInertiaX = 0.0
            BuoyYoke_3.MassMomentOfInertiaY = 0.0
            BuoyYoke_3.MassMomentOfInertiaZ = 0.0
            BuoyYoke_3.CylinderOuterDiameter[0] = 0.27305
            BuoyYoke_3.CylinderInnerDiameter[0] = 0.23658
            BuoyYoke_3.CylinderLength[0]        = 2*abs(conn_y)
            BuoyYoke_3.NormalDragAreaCalculatedFromGeometry     = "Yes"
            BuoyYoke_3.CylinderNormalDragForceCoefficient[0]    = 1.2
            BuoyYoke_3.DampingRelativeTo                        = "Fluid"
            BuoyYoke_3.CylinderNormalAddedMassForceCoefficient[0] = 1.2
            BuoyYoke_3.CylinderAxialAddedMassForceCoefficient[0]  = 1.0
            # Right Leg
            BuoyYoke_1              = model.CreateObject(of.ot6DBuoy, "BuoyYoke_1")
            BuoyYoke_1.BuoyType     = "Towed fish"
            BuoyYoke_1.Connection   = "BuoyYoke_3"
            BuoyYoke_1.InitialX             = 0.0
            BuoyYoke_1.InitialY             = 0.0
            BuoyYoke_1.InitialZ             = -1*BuoyYoke_Length
            BuoyYoke_1.InitialRotation1     = -90.0
            BuoyYoke_1.InitialRotation2     = 0.0
            BuoyYoke_1.InitialRotation3     = -90.0
            BuoyYoke_1.Mass                 = 0.001
            BuoyYoke_1.MassMomentOfInertiaX = 0.0
            BuoyYoke_1.MassMomentOfInertiaY = 0.0
            BuoyYoke_1.MassMomentOfInertiaZ = 0.0
            BuoyYoke_1.CylinderOuterDiameter[0] = 0.27305
            BuoyYoke_1.CylinderInnerDiameter[0] = 0.23658
            BuoyYoke_1.CylinderLength[0]        = BuoyYoke_Length
            BuoyYoke_1.NormalDragAreaCalculatedFromGeometry     = "Yes"
            BuoyYoke_1.CylinderNormalDragForceCoefficient[0]    = 1.2
            BuoyYoke_1.DampingRelativeTo                        = "Fluid"
            BuoyYoke_1.CylinderNormalAddedMassForceCoefficient[0] = 1.2
            BuoyYoke_1.CylinderAxialAddedMassForceCoefficient[0]  = 1.0
            # Left Leg
            BuoyYoke_2              = model.CreateObject(of.ot6DBuoy, "BuoyYoke_2")
            BuoyYoke_2.BuoyType     = "Towed fish"
            BuoyYoke_2.Connection   = "BuoyYoke_3"
            BuoyYoke_2.InitialX             = 2*conn_y  #abs(float(line_dict["buoyGeneral"].get("Connection_Y")))*2
            BuoyYoke_2.InitialY             = 0.0
            BuoyYoke_2.InitialZ             = -1*BuoyYoke_Length
            BuoyYoke_2.InitialRotation1     = -90.0
            BuoyYoke_2.InitialRotation2     = 0.0
            BuoyYoke_2.InitialRotation3     = -90.0
            BuoyYoke_2.Mass                 = 0.001
            BuoyYoke_2.MassMomentOfInertiaX = 0.0
            BuoyYoke_2.MassMomentOfInertiaY = 0.0
            BuoyYoke_2.MassMomentOfInertiaZ = 0.0
            BuoyYoke_2.CylinderOuterDiameter[0] = 0.27305
            BuoyYoke_2.CylinderInnerDiameter[0] = 0.23658
            BuoyYoke_2.CylinderLength[0]        = BuoyYoke_Length
            BuoyYoke_2.NormalDragAreaCalculatedFromGeometry     = "Yes"
            BuoyYoke_2.CylinderNormalDragForceCoefficient[0]    = 1.2
            BuoyYoke_2.DampingRelativeTo                        = "Fluid"
            BuoyYoke_2.CylinderNormalAddedMassForceCoefficient[0] = 1.2
            BuoyYoke_2.CylinderAxialAddedMassForceCoefficient[0]  = 1.0
            # Create Buoy Yoke COG Item
            Buoyyoke_COG        = model.CreateObject(of.ot6DBuoy, "BuoyYokeCOG")
            Buoyyoke_COG.Mass   = BuoyYoke_Weight
            Buoyyoke_COG.MassMomentOfInertiaX = 0
            Buoyyoke_COG.MassMomentOfInertiaY = 0
            Buoyyoke_COG.MassMomentOfInertiaZ = 0
            Buoyyoke_COG.Volume     = 0.1
            Buoyyoke_COG.Height     = 0.1
            Buoyyoke_COG.Connection = "Buoy_Yoke_Hinge"
            Buoyyoke_COG.InitialX   = float(line_dict["buoyGeneral"].get("YokeCOG")) 
            Buoyyoke_COG.InitialY   = conn_y
            Buoyyoke_COG.InitialZ   = 0
            Buoyyoke_COG.InitialRotation1 = 0.0
            Buoyyoke_COG.InitialRotation2 = 0.0
            Buoyyoke_COG.InitialRotation3 = 0.0
            Buoyyoke_COG.PenColour  = 0xFF69B4 # hot pink
            #
            dummySz = 0.1
            Buoyyoke_COG.VertexX = [dummySz, -dummySz, -dummySz, dummySz, dummySz, -dummySz, -dummySz, dummySz]
            Buoyyoke_COG.VertexY = [dummySz, dummySz, -dummySz, -dummySz, dummySz, dummySz, -dummySz, -dummySz]
            Buoyyoke_COG.VertexZ = [dummySz, dummySz, dummySz, dummySz, -dummySz, -dummySz, -dummySz, -dummySz]
            
            # Position the Buoy Attach
            PLET_BuoyAttach.Connection = "Buoy_Yoke_Hinge"
            PLET_BuoyAttach.InitialX   = BuoyYoke_Length
            PLET_BuoyAttach.InitialY   = conn_y  #0.0        #BuoyYokeWidth*0.5
            PLET_BuoyAttach.InitialZ   = 0.0
            PLET_BuoyAttach.InitialRotation1 = 0
            PLET_BuoyAttach.InitialRotation2 = 0
            PLET_BuoyAttach.InitialRotation3 = -90
                    
            # Get Total Length of Yoke Modelled to Calc Unit Mass
            ##Yoke_Length       = float(line_dict["buoyGeneral"].get("LinkYokeLength"))
            ###Yoke_Width        = float(line_dict["structureGeneral"].get("Frame_Width"))
            ##Yoke_Width        = 2*abs(float(line_dict["buoyGeneral"].get("Connection_Y")))
            ##BuoyYoke_Weight   = float(line_dict["buoyGeneral"].get("YokeAirWeight"))
            ###
            ##yoke_len                            = 2*Yoke_Length + Yoke_Width
            ####Buoyyoke_linetype.MassPerUnitLength = BuoyYoke_Weight/yoke_len
            ####Buoyyoke_linetype.EIx, Buoyyoke_linetype.EIy = [30e3, 30e3] 
            ####Buoyyoke_linetype.EA                         = 300e3
            ####Buoyyoke_linetype.PoissonRatio               = 0.3
            ####Buoyyoke_linetype.GJ                         = 40e3
            ####Buoyyoke_linetype.Cdx, Buoyyoke_linetype.Cdy = [2.0, 2.0]        
            ####Buoyyoke_linetype.Cdz                        = 0.008
            ####Buoyyoke_linetype.PenColour                  = 0x088F8F
            
                       
            # Create Yoke Item
            ###BuoyYoke_IDs = [
            ###    constants.BUOY_YOKE_NAME + "_par1",
            ###    constants.BUOY_YOKE_NAME + "_par2",
            ###    constants.BUOY_YOKE_NAME + "_par3"
            ###]
            ###BuoyYoke_1 = model.CreateObject(of.otLine, BuoyYoke_IDs[0])
            ###BuoyYoke_2 = model.CreateObject(of.otLine, BuoyYoke_IDs[1])
            ###BuoyYoke_3 = model.CreateObject(of.otLine, BuoyYoke_IDs[2])   
            ####
            ###set_BuoyYoke = [BuoyYoke_1, BuoyYoke_2, BuoyYoke_3]
            #### 
            ###BuoyYokeLen     = float(line_dict["buoyGeneral"].get("LinkYokeLength"))
            ###BuoyYokeWidth   = float(line_dict["structureGeneral"].get("Frame_Width"))
            ####
            ###for yokeObj in set_BuoyYoke:
            ###    yokeObj.LineType[0]     = "BuoyYoke"
            ###    yokeObj.EndAConnection  = "Buoy_Yoke_Hinge"
            ###    yokeObj.EndBConnection  = "Buoy_Yoke_Hinge"
            ###    yokeObj.StaticsSeabedFrictionPolicy = 'None'
            ###    yokeObj.EndAxBendingStiffness       = 0
            ###    yokeObj.EndBxBendingStiffness       = 0
            ###    yokeObj.EndADeclination             = 90
            ###    yokeObj.EndBDeclination             = 90
            ###    yokeObj.NodePenColour = 0X088F8F
            ###            
            ###BuoyYoke_1.Length[0], BuoyYoke_2.Length[0]                             = [BuoyYokeLen, BuoyYokeLen] 
            ###BuoyYoke_3.Length[0], BuoyYoke_3.TargetSegmentLength[0]                = [BuoyYokeWidth, BuoyYokeWidth]
            ###BuoyYoke_1.TargetSegmentLength[0], BuoyYoke_2.TargetSegmentLength[0]   = [BuoyYokeLen, BuoyYokeLen]
            #
            # --- Buoy Yoke Side Attachment
            ###Buoy_yoke_con = 0.5*BuoyYokeWidth
            ###
            ###BuoyYoke_1.EndAX, BuoyYoke_1.EndAY, BuoyYoke_1.EndAZ   = [          0, -Buoy_yoke_con, 0]
            ###BuoyYoke_1.EndBX, BuoyYoke_1.EndBY, BuoyYoke_1.EndBZ   = [Yoke_Length, -Buoy_yoke_con, 0]
            ###BuoyYoke_1.EndAAzimuth, BuoyYoke_1.EndBAzimuth         = [180, 180]
            ###BuoyYoke_1.EndAGamma, BuoyYoke_1.EndBGamma             = [180, 180]
            ####
            ###BuoyYoke_2.EndAX, BuoyYoke_2.EndAY, BuoyYoke_2.EndAZ   = [          0, Buoy_yoke_con, 0]
            ###BuoyYoke_2.EndBX, BuoyYoke_2.EndBY, BuoyYoke_2.EndBZ   = [Yoke_Length, Buoy_yoke_con, 0]
            ###BuoyYoke_2.EndAAzimuth, BuoyYoke_2.EndBAzimuth         = [180, 180]
            ###BuoyYoke_2.EndAGamma, BuoyYoke_2.EndBGamma             = [180, 180]
            ####
            ###BuoyYoke_3.EndAX, BuoyYoke_3.EndAY, BuoyYoke_3.EndAZ   = [Yoke_Length, -Buoy_yoke_con, 0]
            ###BuoyYoke_3.EndBX, BuoyYoke_3.EndBY, BuoyYoke_3.EndBZ   = [Yoke_Length,  Buoy_yoke_con, 0]
            ###BuoyYoke_3.EndAAzimuth, BuoyYoke_3.EndBAzimuth         = [90, 90]
            ###BuoyYoke_3.EndAGamma, BuoyYoke_3.EndBGamma             = [0, 0]
            ####
            ###PLET_BuoyAttach.Connection = "Buoy_Yoke_Hinge"
            ###PLET_BuoyAttach.InitialX   = BuoyYokeLen
            ###PLET_BuoyAttach.InitialY   = 0.0 #BuoyYokeWidth*0.5
            ###PLET_BuoyAttach.InitialZ   = 0.0
            ###PLET_BuoyAttach.InitialRotation1 = 0
            ###PLET_BuoyAttach.InitialRotation2 = 0
            ###PLET_BuoyAttach.InitialRotation3 = 0

def create_NLModel(
    model       : object,
    line        : object,
    line_dict   : dict,
    vessel_name : str,
    w_depth     : float, 
    stage       : str,
    currentSpeed: float,
    currentDir  : float
    ):
    '''
    Function    :   Creates initial model based on pipe inputs and selected vessel,
                    runs optimisation routine to find static configuration,
                    post-processes results, writes them to a dictionary object.
                    
    Args        :   -model (the model)
                    -line (the pipe line)
                    -line_dict (the job dict)
                    -vessel_name (shortened vessel name, sans 'Seven', in lowercase)
                    -w_depth (water depth)
                    -stage (Stage_1 or Stage_2, depending on mudmat wings)
                    -currentSpeed (current speed, either 0 or 1)
                    -currentDir (current direction, usually 0 or 180)
                    
    Returns     :   -
    '''   
    ramp_angle  = line_dict["vesselGeneral"].get("SelectedRampAngle")     
    RAO_id      = line_dict["vesselGeneral"].get("RAOSelected")
    draught_id  = line_dict["vesselGeneral"].get("DraughtSelected")
    
    #vessel_worst_case_file_path = f"./vessel_database/{vessel_name}/{vessel_name}_assumed_worst_case.json"
    #vessel_worst_case_json      = utils.read_json_file(vessel_worst_case_file_path)
            
    env             = model["Environment"]
    env.WaterDepth  = w_depth
    comment_sep = (
        86 * "="
    ) ## Create separator between base model comments and user comments
    
    model["General"].Comments += f"\n{comment_sep}\n\n" + line_dict["General"].get("Comments")
    model["General"].BuoysIncludedInStatics = "Individually specified"
    
    # ----- Setup the Current Profile
    
    model["Environment"].CurrentRamped          = "No"  ##Ensures that current is included in static calculation             
    model["Environment"].RefCurrentSpeed        = currentSpeed   
    model["Environment"].RefCurrentDirection    = currentDir
    
    current_profile = line_dict["General"].get("CurrentProfile")
    
    model["Environment"].NumberOfCurrentLevels = len(current_profile)
    
    for curItem in range(len(current_profile)):
        model["Environment"].CurrentDepth[curItem]      = float(current_profile[str(curItem)]["CurrentDepth"] )
        model["Environment"].CurrentFactor[curItem]     = float(current_profile[str(curItem)]["CurrentSpeed"] )
        model["Environment"].CurrentRotation[curItem]   = 0.0
         
    model["Environment"].SeabedNormalStiffness  = 10e3
    
    #Set Ramp Angle
    model[f"{vessel_name.capitalize()}-Ramp"].InitialRotation2 = -1 * abs(
        float(ramp_angle)
    )
    model[vessel_name.capitalize()].VesselType  = RAO_id
    model[vessel_name.capitalize()].Draught     = draught_id
    
    def find_catenary_starting_shape(w_depth, ramp_angle):
        """This function estimates the inital pipe length, anchor position & hang-off coordinates based on water depth,

        The general principle is that in Orcaflex, a catenary will find an inital solution provided the belly of the catanery before it has been solved
        rests at around 0.25*WD below seabed level, provided the resulting angle at the top isn't too steep

        First a graph of y = cosh(x) is derived whereby the right side of the graph terminates when the tangent angle is 45° (tan(45)=dy/dx),

        The left side of the graph is symmetrical to the left side only it terminates where the curve crosses the x-axis (anchor position at seabed level)

        Then the curve is scaled so that the top of the curve is located at sea-level and the belly of the curve is below sea-level
        an array of points on the graph is created and the line length is the arc length of the graph
        """
        ramp_angle = float(ramp_angle)
        ## Graph parameters
        if ramp_angle >= 45:
            end_angle = 45
        else:
            end_angle = ramp_angle
        end_angle_rad = math.radians(end_angle)
        graphX_atEnd = math.log(
            (math.sin(end_angle_rad) + 1) / math.cos(end_angle_rad), math.exp(1)
        )
        scale_factor = w_depth / math.cosh(graphX_atEnd)
        if w_depth >= 50:
            stretch_factor = 0.25
        else:
            stretch_factor = 0.50  ## Factor to stretch Y values to achieve strat shape catenary starting from below seabed level and ending at sea-level
        #stretch_factor = 0.25   ## Factor to stretch Y values to achieve strat shape catenary starting from below seabed level and ending at sea-level
        xG0 = -0.8  ##Starting X for unit graph
        gN = 50      # number of points on graph

        # np.cosh: fsolve passes 1-element arrays (math.cosh fails on those with numpy >= 2)
        def find_graphXo(x):
            """Iterate on x value to set catenary y to zero, use scipy fsolve"""
            yG0 = np.cosh(x)
            yC0 = (yG0 - 1) * scale_factor - w_depth * stretch_factor
            return yC0

        xG0 = optimize.fsolve(find_graphXo, xG0)

        def find_graphXinc_setWD(inc):
            """iterate on x increment to set final catenary height (yCn) to water depth, use scipy fsolve"""
            yCn = (
                (np.cosh(xG0[0] + (gN - 1) * inc)) - 1
            ) * scale_factor - w_depth * stretch_factor
            return yCn - w_depth

        graph_inc = optimize.fsolve(find_graphXinc_setWD, 0.05)[0]

        def catenary_(n):
            """Creates X.Y points on graph that describes catenary, belly of catenary will be at X=0"""
            xCn = (xG0[0] + (n) * graph_inc) * scale_factor  ## nth catenary x
            yCn = (
                (math.cosh(xG0[0] + (n) * graph_inc)) - 1
            ) * scale_factor - w_depth * stretch_factor  ## nth catenary y
            return [xCn, yCn]

        arc_graph = [catenary_(i) for i in range(0, gN)]

        ## Create array of segment lengths
        arc_graph_segLengths = [
            math.sqrt(
                (j[0] - arc_graph[i - 1][0]) ** 2 + (j[1] - arc_graph[i - 1][1]) ** 2
            )
            for i, j in enumerate(arc_graph)
            if i != 0
        ]
        x_sBed_pos = arc_graph[0][0]  ## First point
        x_sLevel_pos = arc_graph[-1][0]
        total_lineL = int(sum(arc_graph_segLengths))
        anchor_pos = (
            -1 * (x_sLevel_pos - x_sBed_pos)
        )  # Distance between ends of catenary graph, corresponds to reletive position between anchor and hang-off
        
        # New modification (10/07/2026) to the anchor position, such that not too much pipe is resting on seabed
        amount_to_shorten   = w_depth - 250
        shortenedLineL      = total_lineL - amount_to_shorten
        print(f"Total line length: {total_lineL}, anchor pos: {anchor_pos}")
        #    
        newanchor_pos       = anchor_pos + amount_to_shorten
        #
        total_lineL         = shortenedLineL
        anchor_pos          = newanchor_pos
        
        print(f"Proposed Total line length: {shortenedLineL}, amount to shorten: {amount_to_shorten}, anchor pos: {newanchor_pos}")

        return anchor_pos, total_lineL

    startshape = find_catenary_starting_shape(w_depth, ramp_angle)
    
    anchor_relativepos  = startshape[0]
    pipe_overall_length = startshape[1]
        
    if pipe_overall_length >= 100:
        line.Length[2] = 100 #0.1*pipe_overall_length
        line.Length[3] = 0.33*(pipe_overall_length - line.Length[2] - line.Length[1] - line.Length[0])
        line.Length[4] = 0.33*(pipe_overall_length - line.Length[2] - line.Length[1] - line.Length[0])
        line.Length[5] = 0.33*(pipe_overall_length - line.Length[2] - line.Length[1] - line.Length[0])
    else:
        line.Length[2] = pipe_overall_length * 0.25
        line.Length[3] = pipe_overall_length * 0.25
        line.Length[4] = pipe_overall_length * 0.25
        line.Length[5] = pipe_overall_length * 0.25
                
    ## Set contents of pipe
    if line_dict["pipeGeneral"].get("Content") == "Free flooding":
        line.ContentsMethod = "Free flooding"
    else:
        line.ContentsMethod = "Uniform"
        line.ContentsDensity = line_dict["pipeGeneral"].get("ContentDensity")
        
    ## Setup for line connection to vessel ramp ##
    plet_model = line_dict["structureGeneral"].get("PLETModellingOpt")  
    
    ## Setup for line connection to PLET Frame 
    line.EndAConnection                 = "PLET_Frame"
    if plet_model != "Frame & Mudmat (With Wings)" or stage == "Stage_2":
        line.EndAX                          = line_dict["structureGeneral"].get("AF_XCoor")
        line.EndAY                          = line_dict["structureGeneral"].get("AF_YCoor")
        line.EndAZ                          = line_dict["structureGeneral"].get("AF_ZCoor")
        
    if stage == "Stage_1" and plet_model == "Frame & Mudmat (With Wings)":
        line.EndAX                          = line_dict["structureGeneral"].get("AF_XCoor_WingUp")
        line.EndAY                          = line_dict["structureGeneral"].get("AF_YCoor_WingUp")
        line.EndAZ                          = line_dict["structureGeneral"].get("AF_ZCoor_WingUp")
                
    line.EndAxBendingStiffness          = of.OrcinaInfinity()
    
    ## Setup for line end orientations and initial anchor position ##
    line.EndAAzimuth        = constants.END_A_AZIMUTH
    line.EndADeclination    = constants.END_A_DECLINATION
    line.EndBAzimuth        = constants.END_B_AZIMUTH
    line.EndBDeclination    = constants.END_B_DECLINATION
    line.EndBConnection     = "Anchored"
    #line.LayAzimuth         = constants.LAY_AZIMUTH
    
    ramp_X = (
        model[vessel_name.capitalize()].InitialX
        + model[f"{vessel_name.capitalize()}-Ramp"].InitialX
    )
    
    #model[f"{vessel_name.capitalize()}-Ramp"].NumberOfSupportedLines = 1
    #model[f"{vessel_name.capitalize()}-Ramp"].SupportedLine[0] = pipeID   #need change to AnR
    
    anchor_position  = ramp_X + anchor_relativepos
    line.EndBX       = anchor_position
    
    line.EndBHeightAboveSeabed = 0    
    #
    line = model[constants.PIPE_NAME]
