"""Build the OrcaFlex base model from the (prepared) project input data."""
from pathlib import Path

import numpy as np
import OrcFxAPI as of

from . import vessels


def create_yoke(model, label, length):
    """Creates a stiff line object representing one strut of the buoyancy yoke."""
    yoke_obj = model.CreateObject(of.otLine, f"TA_Yoke [{label}]")
    yoke_obj.NumberOfSections = 1
    yoke_obj.LineType[0] = "Yoke_Strut"
    yoke_obj.Length[0] = length
    yoke_obj.TargetSegmentLength[0] = length
    yoke_obj.StaticsSeabedFrictionPolicy = "None"
    return yoke_obj


def set_yoke_weight(yoke_lt, yokes, weight_in_air, weight_in_water, rho):
    """Sets yoke line type mass / OD so the struts match the total yoke weight in air and water."""
    yoke_lengths = [yoke.CumulativeLength[-1] for yoke in yokes]
    yoke_lt.MassPerUnitLength = weight_in_air / sum(yoke_lengths)
    yoke_lt.OD = np.sqrt(4 * (weight_in_air - weight_in_water) / (rho * np.pi * sum(yoke_lengths)))


def connect_trunnions(trunnion_data, trunnion, var):
    """Connects a trunnion line to the PLET 6D buoy ('primary' or 'secondary')."""
    trunnion.EndAConnection = "PLET_Properties"
    trunnion.EndAX = trunnion_data[var]["xCoordinate"]
    trunnion.EndAY = -trunnion_data[var]["yCoordinate"]
    trunnion.EndAZ = trunnion_data[var]["zCoordinate"]
    trunnion.EndAAzimuth = 0
    trunnion.EndADeclination = 0
    trunnion.EndAGamma = 0
    trunnion.EndAxBendingStiffness = 0
    trunnion.EndBConnection = "PLET_Properties"
    trunnion.EndBX = trunnion_data[var]["xCoordinate"]
    trunnion.EndBY = trunnion_data[var]["yCoordinate"]
    trunnion.EndBZ = trunnion_data[var]["zCoordinate"]
    trunnion.EndBAzimuth = 0
    trunnion.EndBDeclination = 0
    trunnion.EndBGamma = 0
    trunnion.EndBxBendingStiffness = 0
    trunnion.StaticsSeabedFrictionPolicy = "None"


def write_comments(model, general, vessel):
    """Writes project info into General comments.

    The statics step reads the vessel back from the 'Vessel: 7<Name>' line, keep that format.
    """
    text = (
        f'Client: {general["client"]}\n'
        f'Project: {general["project"]}\n'
        f'Pipeline: {general["pipeline"]}\n'
        f'Revision: {general["revision"]}\n'
        f'JobName: {general["jobName"]}\n'
        f'Comments: {general["comments"]}\n'
        f'Vessel: 7{vessel}\n'
    )
    model["General"].Comments = model["General"].Comments + "\n\n\n" + text


def get_rigging_length(fittings, rigging):
    """Total unstretched length of a rigging assembly (list of {fitting, quantity})."""
    length = 0
    for item in rigging:
        fitting = next(row for row in fittings if row["name"] == item["fitting"])
        length += fitting["length"] * item["quantity"]
    return length


def connect_rigging(wire, make_up):
    """Adds the PLET-side (end A) and SIP-side (end B) fittings as attachments on the initiation wire."""
    plet_rigging = make_up["pletSide"]
    sip_rigging = make_up["sipSide"]
    rows = sum(item["quantity"] for item in plet_rigging) + sum(item["quantity"] for item in sip_rigging)
    wire.NumberOfAttachments = rows
    idx = 0
    for side, rigging in (("end A", plet_rigging), ("end B", sip_rigging)):
        for item in rigging:
            for _ in range(item["quantity"]):
                wire.AttachmentType[idx] = item["fitting"]
                wire.AttachmentZ[idx] = 0
                wire.AttachmentzRelativeTo[idx] = side
                idx += 1


def generate_base_model(json_data, vessel, draught, out_folder):
    """Creates the OrcaFlex base model and saves it to `out_folder`. Returns the saved file path."""
    vessel = vessels.vessel_name(vessel)
    vessel_coords = vessels.vessel_coords(vessel)
    if draught is None:
        draught = vessels.draughts(vessel)[0]
    if draught not in vessel_coords["RAO Types"]:
        raise ValueError(f"Draught '{draught}' not available for 7{vessel}. Options: {vessels.draughts(vessel)}")

    model = of.Model(str(vessels.base_model_file(vessel)))

    general = json_data["general"]
    model_id = f"{general['project']}_{general['pipeline']}_{vessel}_Base_Rev{general['revision']}"
    buoyancy_data = json_data["buoyancyData"]
    sip_data = json_data["sipData"]
    input_env = json_data["environment"]
    line_type_data = json_data["lineTypes"]
    wire_data = json_data["wireType"]
    line_data = json_data["lineData"]
    plet_data = json_data["structureData"]
    code_data = json_data["codeChecksData"]
    var_od_data = json_data["variableOD"]

    # General
    write_comments(model, general, vessel)
    ## Statics damping slightly increased to prevent trunnions from solving inside receptacles.
    model["General"].StaticsMinDamping = int(7)
    model["General"].StaticsMaxDamping = int(25)
    model["General"].StaticsMaxIterations = int(3e3)

    # Environment
    model_env = model["Environment"]
    model_env.SeabedType = input_env["seabedType"]
    model_env.SeabedNormalStiffness = input_env["seabedStiffness"]
    model_env.Density = input_env["seaWaterDensity"] / 1000.0
    if input_env["seabedType"] == "Flat":
        model_env.WaterDepth = input_env["waterDepth"]
    else:
        seabed_profile = input_env["seabedProfile"]
        model_env.SeabedOriginX = float(input_env["seabedOrigin"])
        model_env.SeabedProfileNumberOfPoints = len(seabed_profile["depth"])
        for rowi in range(len(seabed_profile["depth"])):
            model_env.SeabedProfileDistanceFromSeabedOrigin[rowi] = float(seabed_profile["distanceFromOrigin"][rowi])
            model_env.SeabedProfileDepth[rowi] = float(seabed_profile["depth"][rowi])

    current = input_env["currentProfile"]
    model_env.NumberOfCurrentLevels = len(current["waterDepth"])
    model_env.CurrentRamped = "No"
    for rowi in range(len(current["waterDepth"])):
        model_env.CurrentDepth[rowi] = float(current["waterDepth"][rowi])
        model_env.CurrentFactor[rowi] = float(current["currentSpeed"][rowi])

    # Variable properties
    ## Bungee rope stiffness
    ea_data = model.CreateObject(of.otAxialStiffness, "AxialStiffness_Bungee")
    ea_data.NumberOfRows = len(wire_data["wireAxialStiffness"]["strain"])
    for rowi in range(ea_data.NumberOfRows):
        ea_data.IndependentValue[rowi] = wire_data["wireAxialStiffness"]["strain"][rowi]
        ea_data.DependentValue[rowi] = wire_data["wireAxialStiffness"]["wallTension"][rowi]
    ## Variable OD
    for profile in var_od_data:
        var_od = model.CreateObject(of.otLineTypeDiameter, profile["profileName"])
        var_od.NumberOfRows = len(profile["profile"]["arcLength"])
        for rowi in range(var_od.NumberOfRows):
            var_od.IndependentValue[rowi] = profile["profile"]["arcLength"][rowi]
            var_od.DependentValue[rowi] = profile["profile"]["diameter"][rowi]

    # Line types
    variable_od_types = set()
    for line_type in line_type_data:
        od_check = isinstance(line_type["outerDiameter"], str)
        if od_check:
            variable_od_types.add(line_type["lineTypeName"])
        lt_obj = model.CreateObject(of.otLineType, line_type["lineTypeName"])
        lt_obj.Category = "Homogeneous pipe"
        lt_obj.OD = line_type["outerDiameter"] if od_check else line_type["outerDiameter"] / 1000
        lt_obj.ID = line_type["innerDiameter"] / 1000
        lt_obj.MaterialDensity = line_type["materialDensity"] / 1000
        if line_type["coatingThickness"] > 0:
            lt_obj.CoatingThickness = line_type["coatingThickness"] / 1000
            lt_obj.CoatingMaterialDensity = line_type["coatingDensity"] / 1000
        if line_type["liningThickness"] > 0:
            lt_obj.LiningThickness = line_type["liningThickness"] / 1000
            lt_obj.LiningMaterialDensity = line_type["liningDensity"] / 1000
        lt_obj.Cdx = line_type["cdx"]
        lt_obj.Cax = line_type["cax"]
        lt_obj.SeabedLateralFrictionCoefficient = line_type["normalFriction"]
        lt_obj.SeabedAxialFrictionCoefficient = line_type["axialFriction"]
        if line_type["materialType"] == "Tabular":
            if not line_type.get("stressStrain"):
                raise ValueError(f"Line type '{line_type['lineTypeName']}' is Tabular but has no stressStrain data")
            ss_obj = model.CreateObject(of.otStressStrainRelationship, f'{line_type["lineTypeName"]}_Stress-Strain')
            ss_obj.CurveType = "Stress-strain table"
            nrows = len(line_type["stressStrain"]["strain"])
            ss_obj.NumOfRows = nrows
            for rowi in range(nrows):
                ss_obj.strain[rowi] = line_type["stressStrain"]["strain"][rowi]
                ss_obj.stress[rowi] = line_type["stressStrain"]["stress"][rowi]
            lt_obj.E = ss_obj.name
        elif line_type["materialType"] == "Ramberg-Osgood":
            ro = line_type["roParams"]
            ss_obj = model.CreateObject(of.otStressStrainRelationship, f'{line_type["lineTypeName"]}_Stress-Strain')
            ss_obj.CurveType = "Ramberg-Osgood curve"
            ss_obj.E = ro["E"]
            ss_obj.RefStress = ro["refStress"]
            ss_obj.K = ro["K"]
            ss_obj.n = ro["n"]
            lt_obj.E = ss_obj.name
        else:
            lt_obj.E = line_type["E"]

    # PLET trunnions
    trunnion_type = model.CreateObject(of.otLineType, "TrunnionLT")
    trunnion_type.Category = "General"
    trunnion_type.OD = 0.001
    trunnion_type.ID = 0.0
    trunnion_type.MassPerUnitLength = 0.001
    trunnion_type.EIx = 10e3
    trunnion_type.EA = 700e3
    trunnion_type.GJ = 80
    trunnion_type.OuterContactDiameter = plet_data["trunnions"]["primary"]["contactDiameter"]

    # Bungee rope
    rope_type = model.CreateObject(of.otLineType, "Bungee_Rope")
    rope_type.Category = "General"
    rope_type.OD = wire_data["wireOuterDiameter"]
    rope_type.ID = 0.0
    rope_type.MassPerUnitLength = wire_data["wireWeightInAir"]
    rope_type.EIx = 1.0
    rope_type.EA = ea_data.name
    rope_type.GJ = 0

    ## Yoke - no real properties
    yoke_type = model.CreateObject(of.otLineType, "Yoke_Strut")
    yoke_type.Category = "General"
    yoke_type.OD = 0.001
    yoke_type.ID = 0.0
    yoke_type.MassPerUnitLength = 0.01
    yoke_type.EIx = 30e3
    yoke_type.EIy = 30e3
    yoke_type.EA = 300e3
    yoke_type.GJ = 40e3

    # Clump types (rigging fittings)
    for item in wire_data["fittings"]:
        fitting = model.CreateObject(of.otClumpType, item["name"])
        fitting.Mass = item["mass"]
        fitting.Volume = item["volume"]
        fitting.Height = item["length"]

    # Lines
    ## Main line
    line_pipe = model.CreateObject(of.otLine, "RigidPipe")
    line_pipe.NumberOfSections = line_data["numberOfLineSegments"]
    for rowi, segment in enumerate(line_data["lineSegments"]):
        line_pipe.LineType[rowi] = segment["sectionLineType"]
        if segment["sectionLineType"] not in variable_od_types:
            line_pipe.Length[rowi] = segment["sectionLength"]
        line_pipe.TargetSegmentLength[rowi] = 1.0
    line_pipe.LayAzimuth = 0

    ## Initiation wire (bungee rope)
    bungee = model.CreateObject(of.otLine, "Initiation")
    bungee.NumberOfSections = 1
    bungee.lineType[0] = "Bungee_Rope"
    bungee.Length[0] = wire_data["wireLength"]
    bungee.TargetSegmentLength[0] = 1.0
    bungee.EndAConnection = "Anchored"
    bungee.EndAX = 5
    bungee.EndAY = 0
    bungee.EndAZ = 2.5
    bungee.EndBConnection = "Anchored"
    bungee.EndBX = -9
    bungee.EndBY = 0
    bungee.EndBZ = 2.5
    bungee.EndAConnection = "Free"
    bungee.EndBConnection = "Free"
    bungee.StaticsSeabedFrictionPolicy = "None"

    ## Trunnions
    trunnion_pri = model.CreateObject(of.otLine, "TrunnionMain")
    trunnion_pri.NumberOfSections = 1
    trunnion_pri.LineType[0] = "TrunnionLT"
    trunnion_pri.Length[0] = plet_data["trunnions"]["primary"]["length"]
    trunnion_pri.TargetSegmentLength[0] = plet_data["trunnions"]["primary"]["length"]
    trunnion_sec = model.CreateObject(of.otLine, "TrunnionSecondary")
    trunnion_sec.NumberOfSections = 1
    trunnion_sec.LineType[0] = "TrunnionLT"
    trunnion_sec.Length[0] = plet_data["trunnions"]["secondary"]["length"]
    trunnion_sec.TargetSegmentLength[0] = plet_data["trunnions"]["secondary"]["length"]

    ## Yoke struts
    yoke_spacing = 2 * abs(plet_data["connectionPoints"]["yokeConnection"]["y"])
    yoke_one = create_yoke(model, "A", buoyancy_data["connectionData"]["yokeLength"])
    yoke_two = create_yoke(model, "B", buoyancy_data["connectionData"]["yokeLength"])
    yoke_three = create_yoke(model, "C", yoke_spacing)
    set_yoke_weight(
        yoke_type, [yoke_one, yoke_two, yoke_three],
        buoyancy_data["connectionData"]["yokeWIA"], buoyancy_data["connectionData"]["yokeWIW"], model_env.Density
    )

    # Shapes
    sip_pile = model.CreateObject(of.otShape, "SIP_Pile")
    sip_pile.ShapeType = "Drawing"
    sip_pile.Shape = "Cylinder"
    sip_pile.Length = 20
    sip_pile.OuterDiameter = sip_data["pileDiameter"]
    sip_pile.InnerDiameter = 0

    receptacle_bot_one = model.CreateObject(of.otShape, "SIP_Receptacle_Bottom_Solid#1")
    receptacle_bot_one.ShapeType = "Elastic Solid"
    receptacle_bot_one.Shape = "Block"
    receptacle_bot_one.SizeX = sip_data["receptacleBackWallDistance"] - sip_data["receptacleFrontWallDistance"]
    receptacle_bot_one.SizeY = sip_data["receptacleWidth"]
    receptacle_bot_one.SizeZ = sip_data["receptacleHeight"]
    receptacle_bot_one.NormalStiffness = 10e3
    receptacle_bot_two = receptacle_bot_one.CreateClone("SIP_Receptacle_Bottom_Solid#2", model)

    front_wall_one = model.CreateObject(of.otShape, "SIP_Receptacle_FrontWall#1")
    front_wall_one.ShapeType = "Elastic Solid"
    front_wall_one.Shape = "Block"
    front_wall_one.SizeX = 0.1
    front_wall_one.SizeY = sip_data["receptacleWidth"]
    front_wall_one.SizeZ = 0.5
    front_wall_one.Rotation3 = 180
    front_wall_one.NormalStiffness = 10e3
    front_wall_two = front_wall_one.CreateClone("SIP_Receptacle_FrontWall#2", model)
    back_wall_one = front_wall_one.CreateClone("SIP_Receptacle_BackWall#1", model)
    back_wall_one.Rotation3 = 0
    back_wall_two = back_wall_one.CreateClone("SIP_Receptacle_BackWall#2", model)

    # 6D buoys
    ## PLET
    hydro = plet_data["hydrodynamics"]
    plet = model.CreateObject(of.ot6DBuoy, "PLET_Properties")
    plet.Connection = "Free"
    plet.Mass = plet_data["weightInAir"]
    plet.MassMomentOfInertiaX = hydro["Ix"]
    plet.MassMomentOfInertiaY = hydro["Iy"]
    plet.MassMomentOfInertiaZ = hydro["Iz"]
    plet.CentreofMassX = plet_data["cogX"]
    plet.CentreofMassY = plet_data["cogY"]
    plet.CentreofMassZ = plet_data["cogZ"]
    plet.Volume = hydro["volume"]
    plet.Height = plet_data["height"]
    plet.CentreOfVolumeX = plet_data["cogX"]
    plet.CentreOfVolumeY = plet_data["cogY"]
    plet.CentreOfVolumeZ = plet_data["cogZ"]
    plet.DragAreaX = hydro["dragAreaX"]
    plet.DragAreaY = hydro["dragAreaY"]
    plet.DragAreaZ = hydro["dragAreaZ"]
    plet.DragForceCoefficientX = hydro["cdX"]
    plet.DragForceCoefficientY = hydro["cdY"]
    plet.DragForceCoefficientZ = hydro["cdZ"]
    plet.AddedMassCoefficientX = hydro["caX"]
    plet.AddedMassCoefficientY = hydro["caY"]
    plet.AddedMassCoefficientZ = hydro["caZ"]
    plet.NumberOfVertices = 8
    for rowi in range(plet.NumberOfVertices):
        plet.VertexX[rowi] = plet.VertexX[rowi] / abs(plet.VertexX[rowi]) * plet_data["length"] / 2
        plet.VertexY[rowi] = plet.VertexY[rowi] / abs(plet.VertexY[rowi]) * plet_data["width"] / 2
        plet.VertexZ[rowi] = plet.VertexZ[rowi] / abs(plet.VertexZ[rowi]) * plet_data["height"] / 2
    plet.Connection = "Anchored"
    plet.InitialZ = 30
    plet.Connection = "Free"

    ## Receptacle support to help with solving static steps
    receptacle_floor = model.CreateObject(of.ot6DBuoy, "SIP_receptacle_floor")
    for rowi in range(receptacle_floor.NumberOfVertices):
        receptacle_floor.VertexX[rowi] = receptacle_floor.VertexX[rowi] / 100
        receptacle_floor.VertexY[rowi] = receptacle_floor.VertexY[rowi] / 100
        receptacle_floor.VertexZ[rowi] = receptacle_floor.VertexZ[rowi] / 100
    ### Negligible properties
    receptacle_floor.BuoyType = 'Lumped'
    receptacle_floor.Mass = 0
    receptacle_floor.MassMomentOfInertiaX = 0
    receptacle_floor.MassMomentOfInertiaY = 0
    receptacle_floor.MassMomentOfInertiaZ = 0
    receptacle_floor.CentreofMassX = 0
    receptacle_floor.CentreofMassY = 0
    receptacle_floor.CentreofMassZ = 0
    receptacle_floor.Volume = 0
    receptacle_floor.CentreOfVolumeX = 0
    receptacle_floor.CentreOfVolumeY = 0
    receptacle_floor.CentreOfVolumeZ = 0

    # Support types
    receptacle_support = model.CreateObject(of.otSupportType, "SIP_Receptacle_Support")
    receptacle_support.Geometry = 'Flat'
    receptacle_support.NormalStiffness = 10e3
    receptacle_support.Diameter = 0.002
    receptacle_support.FlatSupportLength = sip_data["receptacleWidth"]

    # 3D buoys
    module = buoyancy_data["moduleData"]
    plet_buoy = model.CreateObject(of.ot3DBuoy, "PLET_Buoy")
    plet_buoy.Mass = module["moduleWIA"]
    plet_buoy.Volume = module["moduleVolume"]
    plet_buoy.Height = module["moduleHeight"]
    plet_buoy.DragAreaX = module["hydrodynamics"]["dragAreaX"]
    plet_buoy.DragAreaY = module["hydrodynamics"]["dragAreaY"]
    plet_buoy.DragAreaZ = module["hydrodynamics"]["dragAreaZ"]
    plet_buoy.CdX = module["hydrodynamics"]["cdX"]
    plet_buoy.CdY = module["hydrodynamics"]["cdY"]
    plet_buoy.CdZ = module["hydrodynamics"]["cdZ"]
    plet_buoy.CaX = module["hydrodynamics"]["caX"]
    plet_buoy.CaY = module["hydrodynamics"]["caY"]
    plet_buoy.CaZ = module["hydrodynamics"]["caZ"]
    plet_buoy.Connection = "Anchored"
    plet_buoy.InitialZ = 150
    plet_buoy.Connection = "Free"

    # Links
    make_up = wire_data["makeUpRigging"]
    buoy_rigging = model.CreateObject(of.otLink, "Buoyancy_Rigging")
    buoy_rigging.LinkType = "Tether"
    buoy_rigging.UnstretchedLength = module["riggingLength"]
    buoy_rigging.Stiffness = module["riggingAxialStiffness"]
    if make_up["pletSide"]:
        plet_rigging = model.CreateObject(of.otLink, "rigging_PLET")
        plet_rigging.LinkType = "Tether"
        plet_rigging.UnstretchedLength = get_rigging_length(wire_data["fittings"], make_up["pletSide"])
        plet_rigging.Stiffness = 100e3
    if make_up["sipSide"]:
        sip_rigging = model.CreateObject(of.otLink, "rigging_SIP")
        sip_rigging.LinkType = "Tether"
        sip_rigging.UnstretchedLength = get_rigging_length(wire_data["fittings"], make_up["sipSide"])
        sip_rigging.Stiffness = 100e3

    # Constraints
    sip_ref = model.CreateObject(of.otConstraint, "SIP_Pile_Centre_Reference")
    sip_ref.Connection = "Anchored"
    sip_ref.InitialZ = 0
    sip_ref.Hidden = "Yes"
    yoke_padeye = model.CreateObject(of.otConstraint, "PLET_YokePadeye")
    yoke_padeye.Connection = "Anchored"
    yoke_padeye.InitialZ = 0
    yoke_padeye.Connection = "Fixed"
    yoke_padeye.Hidden = "Yes"
    yoke_hinge = model.CreateObject(of.otConstraint, "PLET_YokeHinge")
    yoke_hinge.Connection = "Anchored"
    yoke_hinge.DOFFree[4] = "yes"
    yoke_hinge.InitialZ = 0
    yoke_hinge.Hidden = "Yes"

    # Code checks (DNV-ST-F101)
    f101 = code_data["f101"]
    model_code = model["Code Checks"]
    model_code.DNVSTF101GammaF = f101["gamma_f"]["a"]
    model_code.DNVSTF101GammaE = f101["gamma_e"]["a"]
    model_code.DNVSTF101GammaC = f101["gamma_c"]
    for item in f101["lineTypeFactor"]:
        model[item["name"]].DNVSTF101GammaSCLB = item["gamma_sc_lb"]
        model[item["name"]].DNVSTF101GammaM = item["gamma_m"]
        model[item["name"]].DNVSTF101AlphaFAB = item["alpha_fab"]
        model[item["name"]].DNVSTF101AlphaGW = item["alpha_gw"]
        model[item["name"]].DNVSTF101AlphaPM = item["alpha_pm"]
    for item in f101["lineTypeProperties"]:
        model[item["name"]].DNVSTF101Pmin = item["pMin"] if item["pMin"] != "~" else of.OrcinaDefaultReal()
        model[item["name"]].DNVSTF101T2 = item["t2"] if item["t2"] != "~" else of.OrcinaDefaultReal()
        model[item["name"]].DNVSTF101FY = float(item["fy"])
        model[item["name"]].DNVSTF101FU = float(item["fu"])
        model[item["name"]].DNVSTF101E = item["E"]
        model[item["name"]].DNVSTF101AlphaH = item["alpha_h"]
        model[item["name"]].DNVSTF101O0 = item["f0"]
        model[item["name"]].DNVSTF101SimplifiedStrainLimit = item["simplifiedStrainLimit"]
    for item in f101["craProperties"]:
        model[item["name"]].DNVSTF101TCRA = item["tCRA"]
        model[item["name"]].DNVSTF101FYCRA = item["fyCRA"]
        model[item["name"]].DNVSTF101FUCRA = item["fuCRA"]

    # Connections
    ## Pipe to tower and PLET
    ho, x_ho, y_ho, z_ho = vessels.hang_off(vessel)
    line_pipe.EndAConnection = ho
    line_pipe.EndAX = x_ho
    line_pipe.EndAY = y_ho
    line_pipe.EndAZ = z_ho
    line_pipe.EndAAzimuth = 180.0
    line_pipe.EndADeclination = 90.0
    line_pipe.EndAGamma = 0.0
    line_pipe.EndBConnection = plet.name
    line_pipe.EndBX = plet_data["connectionPoints"]["pipeConnection"]["x"]
    line_pipe.EndBY = plet_data["connectionPoints"]["pipeConnection"]["y"]
    line_pipe.EndBZ = plet_data["connectionPoints"]["pipeConnection"]["z"]
    line_pipe.EndBAzimuth = 180.0
    line_pipe.EndBDeclination = 90.0
    line_pipe.EndBGamma = 0.0
    line_pipe.EndAxBendingStiffness = of.OrcinaInfinity()
    line_pipe.EndBxBendingStiffness = of.OrcinaInfinity()

    ## PLET: trunnions, buoyancy yoke, initiation wire
    yoke = plet_data["connectionPoints"]["yokeConnection"]
    yoke_hinge.Connection = plet.name
    yoke_hinge.InitialX = yoke["x"]
    yoke_hinge.InitialY = 0
    yoke_hinge.InitialZ = yoke["z"]
    yoke_padeye.Connection = plet.name
    yoke_padeye.InitialX = yoke["x"]
    yoke_padeye.InitialY = 0
    yoke_padeye.InitialZ = yoke["z"] + buoyancy_data["connectionData"]["yokeLength"]
    yoke_padeye.Connection = yoke_hinge.name
    for i in range(6):
        yoke_padeye.DOFFree[i] = "No"
    for strut, y_sign in ((yoke_one, -1), (yoke_two, 1)):
        strut.EndAConnection = yoke_hinge.name
        strut.EndAX = 0
        strut.EndAY = y_sign * yoke["y"]
        strut.EndAZ = 0
        strut.EndBConnection = yoke_padeye.name
        strut.EndBX = 0
        strut.EndBY = y_sign * yoke["y"]
        strut.EndBZ = 0
        strut.EndAxBendingStiffness = of.OrcinaInfinity()
        strut.EndBxBendingStiffness = of.OrcinaInfinity()
    yoke_three.EndAConnection = yoke_padeye.name
    yoke_three.EndAX = 0
    yoke_three.EndAY = -yoke["y"]
    yoke_three.EndAZ = 0
    yoke_three.EndBConnection = yoke_padeye.name
    yoke_three.EndBX = 0
    yoke_three.EndBY = yoke["y"]
    yoke_three.EndBZ = 0
    yoke_three.EndAxBendingStiffness = of.OrcinaInfinity()
    yoke_three.EndBxBendingStiffness = of.OrcinaInfinity()

    connect_trunnions(plet_data["trunnions"], trunnion_pri, "primary")
    connect_trunnions(plet_data["trunnions"], trunnion_sec, "secondary")

    sip_pile.Connection = sip_ref.name
    sip_pile.OriginZ = 0
    sip_pile.Declination = 180
    buoy_rigging.EndAConnection = yoke_padeye.name
    buoy_rigging.EndBConnection = plet_buoy.name
    buoy_rigging.EndAX = 0
    buoy_rigging.EndAY = 0
    buoy_rigging.EndAZ = 0
    buoy_rigging.EndBX = 0
    buoy_rigging.EndBY = 0
    buoy_rigging.EndBZ = 0

    padeye = plet_data["connectionPoints"]["padeyeConnection"]
    connect_rigging(bungee, make_up)
    if make_up["pletSide"]:
        plet_rigging.EndAConnection = plet.name
        plet_rigging.EndAX = padeye["x"]
        plet_rigging.EndAY = padeye["y"]
        plet_rigging.EndAZ = padeye["z"]
        plet_rigging.EndBConnection = bungee.name
        plet_rigging.EndBZ = 0
        plet_rigging.EndBzRelativeTo = "End A"
    else:
        bungee.EndAConnection = plet.name
        bungee.EndAX = padeye["x"]
        bungee.EndAY = padeye["y"]
        bungee.EndAZ = padeye["z"]
    if make_up["sipSide"]:
        sip_rigging.EndAConnection = bungee.name
        sip_rigging.EndAZ = 0
        sip_rigging.EndAzRelativeTo = "End B"
        sip_rigging.EndBConnection = sip_ref.name
        sip_rigging.EndBX = -sip_data["hookDistance"]
        sip_rigging.EndBY = 0
        sip_rigging.EndBZ = sip_data["hookElevation"]
    else:
        bungee.EndBConnection = sip_ref.name
        bungee.EndBX = -sip_data["hookDistance"]
        bungee.EndBY = 0
        bungee.EndBZ = sip_data["hookElevation"]

    width = sip_data["receptacleWidth"]
    spacing = sip_data["receptacleSpacing"]
    height = sip_data["receptacleHeight"]
    front_wall_one.Connection = sip_ref.name
    front_wall_one.OriginX = sip_data["receptacleFrontWallDistance"]
    front_wall_one.OriginY = (width + spacing) / 2 + width / 2
    front_wall_one.OriginZ = height

    front_wall_two.Connection = sip_ref.name
    front_wall_two.OriginX = sip_data["receptacleFrontWallDistance"]
    front_wall_two.OriginY = -(width + spacing) / 2 + width / 2
    front_wall_two.OriginZ = height

    back_wall_one.Connection = sip_ref.name
    back_wall_one.OriginX = sip_data["receptacleBackWallDistance"]
    back_wall_one.OriginY = (width + spacing) / 2 - width / 2
    back_wall_one.OriginZ = height

    back_wall_two.Connection = sip_ref.name
    back_wall_two.OriginX = sip_data["receptacleBackWallDistance"]
    back_wall_two.OriginY = -(width + spacing) / 2 - width / 2
    back_wall_two.OriginZ = height

    receptacle_bot_one.Connection = sip_ref.name
    receptacle_bot_one.OriginX = sip_data["receptacleFrontWallDistance"]
    receptacle_bot_one.OriginY = spacing / 2
    receptacle_bot_one.OriginZ = 0

    receptacle_bot_two.Connection = sip_ref.name
    receptacle_bot_two.OriginX = sip_data["receptacleFrontWallDistance"]
    receptacle_bot_two.OriginY = -spacing / 2 - width
    receptacle_bot_two.OriginZ = 0

    receptacle_floor.Connection = sip_ref.name
    receptacle_floor.InitialX = sip_data["receptacleFrontWallDistance"]
    receptacle_floor.InitialY = -(width + spacing) / 2 + width / 2
    receptacle_floor.InitialZ = height
    receptacle_floor.InitialRotation1 = 0
    receptacle_floor.InitialRotation2 = 0
    receptacle_floor.InitialRotation3 = 0
    receptacle_floor.NumberOfSupportsCoordinateSystems = 1
    receptacle_floor.SupportCoordinateSystemName[0] = 'SIP_Receptacle_Floor'
    receptacle_floor.SupportCoordinateSystemPosx[0] = 0
    receptacle_floor.SupportCoordinateSystemPosy[0] = -width / 2
    receptacle_floor.SupportCoordinateSystemPosz[0] = -0.1
    receptacle_floor.SupportCoordinateSystemAzimuth[0] = 0
    receptacle_floor.SupportCoordinateSystemDeclination[0] = 0
    receptacle_floor.SupportCoordinateSystemGamma[0] = 0

    # 10 supports along each receptacle
    receptacle_floor.NumberOfSupports = 20
    support_spacing = np.linspace(0, sip_data["receptacleBackWallDistance"] - sip_data["receptacleFrontWallDistance"], 10)
    for idx in range(len(support_spacing)):
        receptacle_floor.SupportType[idx] = receptacle_support.name
        receptacle_floor.SupportPositionX[idx] = support_spacing[idx]
        receptacle_floor.SupportPositionY[idx] = 0
        receptacle_floor.SupportPositionZ[idx] = 0
        receptacle_floor.SupportType[idx + 10] = receptacle_support.name
        receptacle_floor.SupportPositionX[idx + 10] = support_spacing[idx]
        receptacle_floor.SupportPositionY[idx + 10] = spacing + width
        receptacle_floor.SupportPositionZ[idx + 10] = 0
    receptacle_floor.NumberOfSupportedLines = 1
    receptacle_floor.SupportedLine[0] = line_pipe.name

    # Set ramp pivot directly above pile centre and set draught
    vessel_obj = model[vessel_coords["Name"]]
    ramp = model[vessel_coords["Ramp"]]
    sip_to_vessel = vessel_obj.InitialX - sip_ref.InitialX
    vessel_obj.InitialX = vessel_obj.InitialX + (sip_to_vessel - ramp.InitialX)
    vessel_obj.VesselType = draught

    out_path = Path(out_folder) / f"{model_id}.dat"
    model.SaveData(str(out_path))
    return out_path
