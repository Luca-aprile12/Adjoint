import os, math
import numpy as np
from math import atan, degrees
# import matplotlib.pyplot as plt
# from mpl_toolkits.mplot3d import Axes3D

# Get the script path
script_path = os.path.abspath(__file__)

# Get the directory path
caseDir = os.path.dirname(script_path)

# ================ PARAMETRI =============

#pitch = -1.48	# Angolo pitch (deg)
#zpitch = 0.015		# dZ imposto (m)
#zpitchBase = 0.235	# Raggio ruota (m)
#xpitch = 1.55	# Passo (m)

file_path = "setup.txt"
with open(file_path, "r") as file:
		lines = file.readlines()
		
FRHline = lines[2].split("=")
if len(FRHline) > 1:
	FRH = float(FRHline[1].strip())
else:
	print("Errore: nessun valore assegnato a FRH\n")

RRHline = lines[3].split("=")
if len(RRHline) > 1:
	RRH = float(RRHline[1].strip())
else:
	print("Errore: nessun valore assegnato a RRH\n")

rollline = lines[4].split("=")
if len(rollline) > 1:
	roll = float(rollline[1].strip())
else:
	print("Errore: nessun valore assegnato a roll\n")

yawline = lines[5].split("=")
if len(yawline) > 1:
	yaw = float(yawline[1].strip())
else:
	print("Errore: nessun valore assegnato a yaw\n")

steerline = lines[6].split("=")
if len(steerline) > 1:
	steer = float(steerline[1].strip())
else:
	print("Errore: nessun valore assegnato a steer\n")

regZline = lines[7].split("=")
if len(steerline) > 1:
	regZ = float(regZline[1].strip())
else:
	print("Errore: nessun valore assegnato a RegZ\n")

AoAline = lines[8].split("=")
if len(steerline) > 1:
	AoAFW = float(AoAline[1].strip())
else:
	print("Errore: nessun valore assegnato a AoA\n")

attfrontline = lines[9]
if len(steerline) > 1:
	start_index = attfrontline.find('(')
	end_index = attfrontline.find(')')+1

	extracted_array_str = attfrontline[start_index:end_index].strip('()')
	array_elements = extracted_array_str.split()
	array_floats = [float(element) for element in array_elements]
	attfront = np.array(array_floats)
else:
	print("Errore: nessun valore assegnato a AttFront\n")

attrearline = lines[10]
if len(steerline) > 1:
	start_index = attrearline.find('(')
	end_index = attrearline.find(')')+1

	extracted_array_str = attrearline[start_index:end_index].strip('()')
	array_elements = extracted_array_str.split()
	array_floats = [float(element) for element in array_elements]
	attrear = np.array(array_floats)
else:
	print("Errore: nessun valore assegnato a AttFront\n")

file.close()

file_path = "setup_UBJ_LBJ.txt"
with open(file_path, "r") as file:
		lines = file.readlines()

steerline = lines[7]
if len(steerline) > 1:
	start_index = steerline.find('(')
	end_index = steerline.find(')')+1

	extracted_array_str = steerline[start_index:end_index].strip('()')
	array_elements = extracted_array_str.split()
	array_floats = [float(element) for element in array_elements]
	UBJ_R = np.array(array_floats)
else:
	print("Errore: nessun valore assegnato a steer\n")	

steerline = lines[8]
if len(steerline) > 1:
	start_index = steerline.find('(')
	end_index = steerline.find(')')+1

	extracted_array_str = steerline[start_index:end_index].strip('()')
	array_elements = extracted_array_str.split()
	array_floats = [float(element) for element in array_elements]
	LBJ_R = np.array(array_floats)
else:
	print("Errore: nessun valore assegnato a steer\n")

steerline = lines[9]
if len(steerline) > 1:
	start_index = steerline.find('(')
	end_index = steerline.find(')')+1

	extracted_array_str = steerline[start_index:end_index].strip('()')
	array_elements = extracted_array_str.split()
	array_floats = [float(element) for element in array_elements]
	UBJ_L = np.array(array_floats)
else:
	print("Errore: nessun valore assegnato a steer\n")	

steerline = lines[10]
if len(steerline) > 1:
	start_index = steerline.find('(')
	end_index = steerline.find(')')+1

	extracted_array_str = steerline[start_index:end_index].strip('()')
	array_elements = extracted_array_str.split()
	array_floats = [float(element) for element in array_elements]
	LBJ_L = np.array(array_floats)
else:
	print("Errore: nessun valore assegnato a steer\n")

#FRH = 20				# distanza tra piano di riferimento e ground sull'asse front
#RRH = 30				# distanza tra piano di riferimento e ground sull'asse rear
					# il ref_plane è la superficie inferiore del telaio 
#roll = 0				# angolo rollio, asse x di configurazione CFD
#yaw = 0					# angolo imbardata. asse z
#steer = 0				# angolo steer

zpitchBase = 0.203			# Raggio ruota (m)
xpitch = 1.53				# Passo (m)
pitch=-degrees(atan((RRH-FRH)/(xpitch*1000)))	# angolo pitch (°)
zpitch=RRH/1000-0.035			# dZ imposto su RRH (m)

# R_axis = np.subtract(UBJ_R, LBJ_R)			# asse ruota left
# R_axis_norm = np.linalg.norm(R_axis)		# norma asse ruota left
# R_versor = np.divide(R_axis, R_axis_norm)	# versore asse ruota left

# L_axis = np.subtract(UBJ_L, LBJ_L)			# asse ruota right
# L_axis_norm = np.linalg.norm(L_axis)		# norma asse ruota right
# L_versor = np.divide(L_axis, L_axis_norm)	# versore asse ruota right

L_axis = UBJ_L - LBJ_L				# asse ruota left
L_norm = np.linalg.norm(L_axis)		# norma asse ruota left
L_versor = L_axis / L_norm			# versore asse ruota left

R_axis = UBJ_R - LBJ_R				# asse ruota right
R_norm = np.linalg.norm(R_axis)		# norma asse ruota right
R_versor = R_axis / R_norm			# versore asse ruota right

#pitch = -0.18724	# Angolo pitch (deg)
#zpitch = -0.01		# dZ imposto (m)
#zpitchBase = 0.203	# Raggio ruota (m)
#xpitch = 1.53	# Passo (m)

L = attrear[0] - attfront[0]			# distanza in x tra attacchini [m]
#passoreg = 5							# mm di cambio altezza per ogni regolazione [mm]
dz = regZ/1000							# variazione altezza z [m]
L1 = 0.19481							# distanza in x tra attacchini DP14
AoAFWvero = degrees(atan(math.tan(np.radians(AoAFW))*L1/L))	# AoA vero di regolazione


# ====================================
os.system("rm constant/triSurface/*")

os.system("cp -a constant/triSurface_0deg/. constant/triSurface/")

os.chdir("constant/triSurface")

# ============================================================= pitch
def setupFW():
	print("\n")
	print("Angolo di pitch FW (regolazione): %.3f gradi (rot asse -y)"%-AoAFW)
	print("Angolo di pitch FW (vero): %.3f gradi (rot asse -y)"%-AoAFWvero)
	print("VAriazione di altezza FW: %d mm"%regZ)
	print("Pitching FW")
	for MS in ["FW"]:
		print("\t"+MS)
		cmd1 = "surfaceTransformPoints -translate '("+str(-attrear[0])+" 0 "+str(-attrear[2])+")' "+MS+".obj "+MS+".obj > mock"
		cmd2 = "surfaceTransformPoints -rollPitchYaw '(0 "+str(AoAFWvero)+" 0)' "+MS+".obj "+MS+".obj > mock"
		cmd3 = "surfaceTransformPoints -translate '("+str(attrear[0])+" 0 "+str(attrear[2]+dz)+")' "+MS+".obj "+MS+".obj > mock"
		os.system(cmd1)
		os.system(cmd2)
		os.system(cmd3)

def setup():
	print("FRH: %.1f mm"%FRH)
	print("RRH: %.1f mm"%RRH)
	print("Angolo di pitch: %.3f gradi"%pitch)
	print("Angolo di roll: %.3f gradi"%roll)
	print("Angolo di yaw: %.3f gradi"%yaw)
	print("Angolo di steer: %.3f gradi"%steer)
	print("Pitching")
	for MS in ["FW"]:
		print("\t"+MS)
		cmd1 = "surfaceTransformPoints -translate '(-"+str(xpitch)+" 0 -"+str(zpitchBase)+")' "+MS+".obj "+MS+".obj > mock"
		cmd2 = "surfaceTransformPoints -rollPitchYaw '(0 "+str(pitch)+" 0)' "+MS+".obj "+MS+".obj > mock"
		cmd3 = "surfaceTransformPoints -translate '("+str(xpitch)+" 0 "+str(zpitchBase+zpitch)+")' "+MS+".obj "+MS+".obj > mock"
		os.system(cmd1)
		os.system(cmd2)
		os.system(cmd3)
	
	print("Rolling")
	for MS in ["FW"]:
		print("\t"+MS)
		cmd1 = "surfaceTransformPoints -rollPitchYaw '("+str(roll)+" 0 0)' "+MS+".obj "+MS+".obj > mock"
		os.system(cmd1)
	
	LBJ_Rx = -LBJ_R[0]		# componenti di LBJ cambiate di segno altrimenti se componente è negativa poi sbarella sotto
	LBJ_Ry = -LBJ_R[1]
	LBJ_Rz = -LBJ_R[2]
	print("Steering")
#	for MS in ["FR_Wheel","Tyre_Plinth_FR"]:
#		print("\t"+MS)
#		cmd1 = "surfaceTransformPoints -translate '("+str(LBJ_Rx)+" "+str(LBJ_Ry)+" "+str(LBJ_Rz)+")' "+MS+".obj "+MS+".obj > mock"
#		cmd2 = "surfaceTransformPoints -rotate-angle '(("+str(R_axis[0])+" "+str(R_axis[1])+" "+str(R_axis[2])+") "+str(steer)+")' "+MS+".obj "+MS+".obj > mock"
#		cmd3 = "surfaceTransformPoints -translate '("+str(LBJ_R[0])+" "+str(LBJ_R[1])+" "+str(LBJ_R[2])+")' "+MS+".obj "+MS+".obj > mock"
#		os.system(cmd1)
#		os.system(cmd2)
#		os.system(cmd3)
	
	LBJ_Lx = -LBJ_L[0]		# componenti di LBJ cambiate di segno altrimenti se componente è negativa poi sbarella sotto
	LBJ_Ly = -LBJ_L[1]
	LBJ_Lz = -LBJ_L[2]
#	for MS in ["FL_Wheel","Tyre_Plinth_FL"]:
#		print("\t"+MS)
#		cmd1 = "surfaceTransformPoints -translate '("+str(LBJ_Lx)+" "+str(LBJ_Ly)+" "+str(LBJ_Lz)+")' "+MS+".obj "+MS+".obj > mock"
#		cmd2 = "surfaceTransformPoints -rotate-angle '(("+str(R_axis[0])+" "+str(R_axis[1])+" "+str(R_axis[2])+") "+str(steer)+")' "+MS+".obj "+MS+".obj > mock"
#		cmd3 = "surfaceTransformPoints -translate '("+str(LBJ_L[0])+" "+str(LBJ_L[1])+" "+str(LBJ_L[2])+")' "+MS+".obj "+MS+".obj > mock"
#		os.system(cmd1)
#		os.system(cmd2)
#		os.system(cmd3)

	print("Yawing")
	for MS in ["FW"]:
		print("\t"+MS)
		cmd1 = "surfaceTransformPoints -rollPitchYaw '(0 0 "+str(yaw)+")' "+MS+".obj "+MS+".obj > mock"
		os.system(cmd1)
	
file_path = caseDir+"/initialConditions"
with open(file_path, "r") as file:
	lines = file.readlines()


def split_and_get_array(index_line):
	line = lines[index_line]
	start_index = line.find('(')
	end_index = line.find(')')+1

	extracted_array_str = line[start_index:end_index].strip('()')
	array_elements = extracted_array_str.split()
	array_floats = [float(element) for element in array_elements]
	numpy_array = np.array(array_floats)
    
	#print(numpy_array) #check

	return numpy_array

FLCenter = split_and_get_array(43)
FLaxis =split_and_get_array(44)
FRCenter = split_and_get_array(47)
FRaxis = split_and_get_array(48)
RLCenter = split_and_get_array(51)
RLaxis = split_and_get_array(52)
RRCenter = split_and_get_array(55)
RRaxis = split_and_get_array(56)





def rotation_tensor_z(alpha_z):
    cos_az = np.cos(alpha_z)
    sin_az = np.sin(alpha_z)
    return np.array([
        [cos_az, -sin_az, 0],
        [sin_az, cos_az, 0],
        [0, 0, 1]
    ])



yaw_rad = np.radians(yaw) 
steer_rad = np.radians(steer)



def fa_cose_in_yaw(ang_yaw, LF_center, LF_axis, RF_center, RF_axis, LR_center, LR_axis, RR_center, RR_axis):
	yaw_tensor = rotation_tensor_z(ang_yaw)
	FLCenter_yaw = np.dot(yaw_tensor, LF_center)
	FLaxis_yaw = np.dot(yaw_tensor, LF_axis)
	FRCenter_yaw = np.dot(yaw_tensor, RF_center)
	FRaxis_yaw = np.dot(yaw_tensor,RF_axis)
	RLCenter_yaw = np.dot(yaw_tensor,LR_center)
	RLaxis_yaw = np.dot(yaw_tensor, LR_axis)
	RRCenter_yaw = np.dot(yaw_tensor,RR_center)
	RRaxis_yaw = np.dot(yaw_tensor,RR_axis)

	return np.array([FLCenter_yaw, FLaxis_yaw, FRCenter_yaw,  FRaxis_yaw, RLCenter_yaw, RLaxis_yaw, RRCenter_yaw, RRaxis_yaw])
	
'''
# check
print(np.linalg.norm(FLCenter))
print(np.linalg.norm(FLCenter_yaw))
print(np.linalg.norm(FLaxis))
print(np.linalg.norm(FLaxis_yaw))'''





#print(FLCenter_yaw)
#print(FLaxis_yaw)
'''
fig = plt.figure()
ax = fig.add_subplot(111, projection='3d')
origin = np.array([0, 0, 0])

# Plot the vector
ax.quiver(*origin, *FLCenter_yaw, color=np.random.rand(3,), arrow_length_ratio=0.1)
ax.quiver(*origin, *FLCenter, color=np.random.rand(3,), arrow_length_ratio=0.1)

ax.set_xlabel('X')
ax.set_ylabel('Y')
ax.set_zlabel('Z')

ax.set_xlim([-1, 1])
ax.set_ylim([-1, 1])
ax.set_zlim([-1, 1])
plt.show()'''


'''
for line in file:
	if "FLCenter          " in line:
				split_line = line.strip().split("	")
				FLCenter = split_line[1].strip()
				print(FLCenter)'''

def rotation_tensor_steer(theta, versor = np.array([0, 0, 0])):
	cos_az = np.cos(theta)
	sin_az = np.sin(theta)
	x = versor[0]
	y = versor[1]
	z = versor[2]
	return np.array([
		[x**2 +(1-x**2)*cos_az, x*y*(1-cos_az)-z*sin_az, x*z*(1-cos_az) + y*sin_az],
		[x*y*(1-cos_az) + z*sin_az, y**2 + (1-y**2)*cos_az, y*z*(1-cos_az) - x*sin_az],
		[x*z*(1-cos_az) - y*sin_az, y*z*(1-cos_az) + x*sin_az, z**2 + (1-z**2)*cos_az]
	])


def fa_cose_in_sterzata(ang_steer, left_center, left_axis, right_center, right_axis):	
	steer_tensor_right = rotation_tensor_steer(ang_steer, R_versor)
	steer_tensor_left = rotation_tensor_steer(ang_steer, L_versor)
	left_center_steer = np.dot(steer_tensor_left, left_center-LBJ_L)
	left_center_steer = left_center_steer + LBJ_L
	left_axis_steer = np.dot(steer_tensor_left, left_axis)
	right_center_steer = np.dot(steer_tensor_right, right_center-LBJ_R)
	right_center_steer = right_center_steer + LBJ_R
	right_axis_steer = np.dot(steer_tensor_right, right_axis)

	return np.array([left_center_steer, left_axis_steer, right_center_steer, right_axis_steer])




# centers_axis_yaw = fa_cose_in_yaw(yaw_rad, FLCenter, FLaxis, FRCenter, FRaxis, RLCenter, RLaxis, RRCenter, RRaxis)
# boh1 = centers_axis_yaw[0]
# boh2 = centers_axis_yaw[1]
# boh3 = centers_axis_yaw[2]
# boh4 = centers_axis_yaw[3]
# centers_axis_front_steer = fa_cose_in_sterzata(steer_rad, boh1, boh2, boh3, boh4)




# FLCenter_fin = centers_axis_front_steer[0]
# FLaxis_fin = centers_axis_front_steer[1]
# FRCenter_fin = centers_axis_front_steer[2]
# FRaxis_fin = centers_axis_front_steer[3]
# RLCenter_fin = centers_axis_yaw[4]
# RLaxis_fin = centers_axis_yaw[5]
# RRCenter_fin = centers_axis_yaw[6]
# RRaxis_fin = centers_axis_yaw[7]

centers_axis_front_steer = fa_cose_in_sterzata(steer_rad, FLCenter, FLaxis, FRCenter, FRaxis)
boh1 = centers_axis_front_steer[0]
boh2 = centers_axis_front_steer[1]
boh3 = centers_axis_front_steer[2]
boh4 = centers_axis_front_steer[3]
centers_axis_yaw = fa_cose_in_yaw(yaw_rad, boh1, boh2, boh3, boh4, RLCenter, RLaxis, RRCenter, RRaxis)




FLCenter_fin = centers_axis_yaw[0]
FLaxis_fin = centers_axis_yaw[1]
FRCenter_fin = centers_axis_yaw[2]
FRaxis_fin = centers_axis_yaw[3]
RLCenter_fin = centers_axis_yaw[4]
RLaxis_fin = centers_axis_yaw[5]
RRCenter_fin = centers_axis_yaw[6]
RRaxis_fin = centers_axis_yaw[7]



# DEBUGGING INUTILE
'''
print(np.linalg.norm(FLCenter))
print(np.linalg.norm(FLCenter_fin))
print(np.linalg.norm(FLaxis))
print(np.linalg.norm(FLaxis_fin))

print(np.linalg.norm(FRCenter))
print(np.linalg.norm(FRCenter_fin))
print(np.linalg.norm(FRaxis))
print(np.linalg.norm(FRaxis_fin))

print(np.linalg.norm(RLCenter))
print(np.linalg.norm(RLCenter_fin))
print(np.linalg.norm(RLaxis))
print(np.linalg.norm(RLaxis_fin))

print(np.linalg.norm(RRCenter))
print(np.linalg.norm(RRCenter_fin))
print(np.linalg.norm(RRaxis))
print(np.linalg.norm(RRaxis_fin))
'''


# VALORI DEFINITIVI POST YAW + STEER

# FLCenter = centers_axis_front_steer[0]
# FLAxis = centers_axis_front_steer[1]
# FRCenter = centers_axis_front_steer[2]
# FRAxis = centers_axis_front_steer[3]

FLCenter = centers_axis_yaw[0]
FLaxis = centers_axis_yaw[1]
FRCenter = centers_axis_yaw[2]
FRaxis = centers_axis_yaw[3]
RLCenter = centers_axis_yaw[4]
RLaxis = centers_axis_yaw[5]
RRCenter = centers_axis_yaw[6]
RRaxis = centers_axis_yaw[7]

print("\nNUOVI CENTRI E ASSI RUOTA:\n")
formatted_string = f"\tFLCenter: (%.7f %.7f %.7f)" % tuple(FLCenter)
print(formatted_string)
formatted_string = f"\tFLaxis: (%.7f %.7f %.7f)" % tuple(FLaxis)
print(formatted_string)
print("\n")
formatted_string = f"\tFRCenter: (%.7f %.7f %.7f)" % tuple(FRCenter)
print(formatted_string)
formatted_string = f"\tFRaxis: (%.7f %.7f %.7f)" % tuple(FRaxis)
print(formatted_string)
print("\n")
formatted_string = f"\tRLCenter: (%.7f %.7f %.7f)" % tuple(RLCenter)
print(formatted_string)
formatted_string = f"\tRLaxis: (%.7f %.7f %.7f)" % tuple(RLaxis)
print(formatted_string)
print("\n")
formatted_string = f"\tRRCenter: (%.7f %.7f %.7f)" % tuple(RRCenter)
print(formatted_string)
formatted_string = f"\tRRaxis: (%.7f %.7f %.7f)" % tuple(RRaxis)
print(formatted_string)
print("\n")


if __name__=="__main__":
	setupFW()

if __name__=="__main__":
	setup()

