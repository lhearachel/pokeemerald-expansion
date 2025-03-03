from itertools import chain

import glob
import re
import json
import os

import time

# before all else, abort if the config is off
with open("./include/config/pokemon.h", "r") as file:
    learnset_config = re.findall(r"#define P_LEARNSET_HELPER_TEACHABLE *([^ ]*)", file.read())
    if len(learnset_config) != 1:
        quit()
    if learnset_config[0] != "TRUE":
        quit()

def parse_mon_name(name):
    return re.sub(r'(?!^)([A-Z]+)', r'_\1', name).upper()

# get compatibility from jsons
def construct_compatibility_dict(force_custom_check):
    dict_out = {}
    for pth in glob.glob('./tools/learnset_helpers/porymoves_files/sv_custom.json'):
        f = open(pth, 'r')
        dict_out = json.load(f)
        dict_out = {mon: set(moves) for mon, moves in dict_out.items()}

    # if the file was not previously generated, check if there is custom data there that needs to be preserved
    with open("./src/data/pokemon/teachable_learnsets.h", 'r') as file:
        raw = file.read()
        if not "// DO NOT MODIFY THIS FILE!" in raw and force_custom_check == True:
            custom_teachable_compatibilities = {}
            for entry in re.findall(r"static const u16 s(.*)TeachableLearnset\[\] = {\n((.|\n)*?)\n};", raw):
                monname = parse_mon_name(entry[0])
                if monname == "NONE":
                    continue
                compatibility = entry[1].split("\n")
                if not monname in custom_teachable_compatibilities:
                    custom_teachable_compatibilities[monname] = []
                if not monname in dict_out:
                    # this mon is unknown, so all data needs to be preserved
                    for move in compatibility:
                        move = move.replace(",", "").strip()
                        if move == "" or move == "MOVE_UNAVAILABLE":
                            continue
                        custom_teachable_compatibilities[monname].append(move)
                else:
                    # this mon is known, so check if the moves in the old teachable_learnsets.h are not in the jsons
                    for move in compatibility:
                        move = move.replace(",", "").strip()
                        if move == "" or move == "MOVE_UNAVAILABLE":
                            continue
                        if not move in dict_out[monname]:
                            custom_teachable_compatibilities[monname].append(move)
            # actually store the data in custom.json
            if os.path.exists("./tools/learnset_helpers/porymoves_files/custom.json"):
                f2 = open("./tools/learnset_helpers/porymoves_files/custom.json", "r")
                custom_json = json.load(f2)
                f2.close()
            else:
                custom_json = {}
            for x in custom_teachable_compatibilities:
                if len(custom_teachable_compatibilities[x]) == 0:
                    continue
                if not x in custom_json:
                    custom_json[x] = {"LevelMoves": [], "PreEvoMoves": [], "TMMoves": [], "EggMoves": [], "TutorMoves": []}
                for move in custom_teachable_compatibilities[x]:
                    custom_json[x]["TutorMoves"].append(move)
                f2 = open("./tools/learnset_helpers/porymoves_files/custom.json", "w")
                f2.write(json.dumps(custom_json, indent=2))
                f2.close()
            print("FIRST RUN: Updated custom.json with teachable_learnsets.h's data")
            # rerun the process
            dict_out = construct_compatibility_dict(False)
    return dict_out

tm_moves = []
tutor_moves = []

time_00_start = time.perf_counter_ns(), time.process_time_ns()

# scan incs
incs_to_check =  glob.glob('./data/scripts/*.inc') # all .incs in the script folder
incs_to_check += glob.glob('./data/maps/*/scripts.inc') # all map scripts

time_01_glob_incs = time.perf_counter_ns(), time.process_time_ns()

if len(incs_to_check) == 0: # disabled if no jsons present
    quit()

for file in incs_to_check:
    with open(file, 'r') as f2:
        raw = f2.read()
    if 'special ChooseMonForMoveTutor' in raw:
        for x in re.findall(r'setvar VAR_0x8005, (MOVE_.*)', raw):
            if not x in tutor_moves:
                tutor_moves.append(x)

time_02_scan_incs = time.perf_counter_ns(), time.process_time_ns()

# scan TMs and HMs
with open("./include/constants/tms_hms.h", 'r') as file:
    for x in re.findall(r'F\((.*)\)', file.read()):
        if not 'MOVE_' + x in tm_moves:
            tm_moves.append('MOVE_' + x)

teachable_moves = set(tm_moves) | set(tutor_moves)

time_03_scan_tms = time.perf_counter_ns(), time.process_time_ns()

# look up universal moves to exclude them
universal_moves = []
with open("./src/pokemon.c", "r") as file:
    for x in re.findall(r"static const u16 sUniversalMoves\[\] =(.|\n)*?{((.|\n)*?)};", file.read())[0]:
        x = x.replace("\n", "")
        for y in x.split(","):
            y = y.strip()
            if y == "":
                continue
            universal_moves.append(y)

time_04_excl_common = time.perf_counter_ns(), time.process_time_ns()

compatibility_dict = construct_compatibility_dict(True)

time_05_build_compats = time.perf_counter_ns(), time.process_time_ns()

# actually prepare the file
with open("./src/data/pokemon/teachable_learnsets.h", 'r') as file:
    out = file.read()
    # list_of_mons = re.findall(r'static const u16 s(.*)TeachableLearnset', out)

# SUB_PAT = re.compile(r'static const u16 s%sTeachableLearnset\[\] = {[\s\S]*?};')
lf = '\n'
lf_tab = ',\n    '

SPECIES_TEACHABLE_PAT = re.compile(r'static const u16 s(?P<species>.+)TeachableLearnset\[\] = {[\s\S]*?};')
new_out = ""
cursor = 0
for match in SPECIES_TEACHABLE_PAT.finditer(out):
    m_start, m_end = match.span()
    species = match.group('species')
    species_cap = parse_mon_name(species)

    # Suppress NONE (which learns nothing) and MEW (which learns everything)
    if species_cap == "NONE" or species_cap == "MEW":
        continue
    if species_cap not in compatibility_dict:
        print(f"Unable to find {species} in json")
        continue

    # Pre-print everything up to the match
    new_out += out[cursor:m_start]
    cursor += m_end

    # Compute the teachable set for this species
    species_teachables = sorted(filter(
        lambda move: move not in universal_moves and move in teachable_moves,
        compatibility_dict[species_cap]
    ))

    # Append to the new output
    entry = f"static const u16 s{species}TeachableLearnset[] = {{{lf}    {lf_tab.join(chain(species_teachables, ('MOVE_UNAVAILABLE',)))},{lf}}};"
    new_out += entry

# for mon in list_of_mons:
#     mon_parsed = parse_mon_name(mon)
#     if mon_parsed == "NONE" or mon_parsed == "MEW":
#         continue
#     if mon_parsed not in compatibility_dict:
#         print("Unable to find %s in json" % mon)
#         continue
#
#     teachables = sorted(filter(
#         lambda move: move not in universal_moves and (move in tm_moves or move in tutor_moves),
#         compatibility_dict[mon_parsed]
#     ))
#
#     repl = f"static const u16 s{mon}TeachableLearnset[] = {{{lf}    {lf_tab.join(chain(teachables, ('MOVE_UNAVAILABLE',)))},{lf}}};"
#     newout = re.sub(r'static const u16 s%sTeachableLearnset\[\] = {[\s\S]*?};' % mon, repl, out)
#     if newout != out:
#         out = newout
#         print("Updated %s" % mon)

time_06_build_output = time.perf_counter_ns(), time.process_time_ns()

# add/update header
header = "//\n// DO NOT MODIFY THIS FILE! It is auto-generated from tools/learnset_helpers/teachable.py\n//\n\n"
longest_move_name = 0
for move in tm_moves + tutor_moves:
    if len(move) > longest_move_name:
        longest_move_name = len(move)
longest_move_name += 2 # + 2 for a hyphen and a space

universal_title = "Near-universal moves found in sUniversalMoves:"
tmhm_title = "TM/HM moves found in \"include/constants/tms_hms.h\":"
tutor_title = "Tutor moves found in map scripts:"

if longest_move_name < len(universal_title):
    longest_move_name = len(universal_title)
if longest_move_name < len(tmhm_title):
    longest_move_name = len(tmhm_title)
if longest_move_name < len(tutor_title):
    longest_move_name = len(tutor_title)

def header_print(str):
    global header
    header += "// " + str + " " * (longest_move_name - len(str)) + " //\n"

header += "// " + longest_move_name * "*" + " //\n"
header_print(tmhm_title)
for move in tm_moves:
    header_print("- " + move)
header += "// " + longest_move_name * "*" + " //\n"
header_print(tutor_title)
tutor_moves.sort() # alphabetically sort tutor moves for easier referencing
for move in tutor_moves:
    header_print("- " + move)
header += "// " + longest_move_name * "*" + " //\n"
header_print(universal_title)
universal_moves.sort() # alphabetically sort near-universal moves for easier referencing
for move in universal_moves:
    header_print("- " + move)
header += "// " + longest_move_name * "*" + " //\n\n"

if not "// DO NOT MODIFY THIS FILE!" in new_out:
    new_out = header + new_out
else:
    new_out = re.sub(r"\/\/\n\/\/ DO NOT MODIFY THIS FILE!(.|\n)*\* \/\/\n\n", header, new_out)

with open("./src/data/pokemon/teachable_learnsets.h", 'w') as file:
    file.write(new_out)

time_07_write_output = time.perf_counter_ns(), time.process_time_ns()

print( "| step          | real time (ns) | cpu time (ns) |")
print( "| ------------- | -------------- | ------------- |")
print(f"| glob .incs    | {time_01_glob_incs[0] - time_00_start[0]: >14} | {time_01_glob_incs[1] - time_00_start[1]: >13} |")
print(f"| scan .incs    | {time_02_scan_incs[0] - time_01_glob_incs[0]: >14} | {time_02_scan_incs[1] - time_01_glob_incs[1]: >13} |")
print(f"| scan TMs      | {time_03_scan_tms[0] - time_02_scan_incs[0]: >14} | {time_03_scan_tms[1] - time_02_scan_incs[1]: >13} |")
print(f"| excl. common  | {time_04_excl_common[0] - time_03_scan_tms[0]: >14} | {time_04_excl_common[1] - time_03_scan_tms[1]: >13} |")
print(f"| build compat  | {time_05_build_compats[0] - time_04_excl_common[0]: >14} | {time_05_build_compats[1] - time_04_excl_common[1]: >13} |")
print(f"| build output  | {time_06_build_output[0] - time_05_build_compats[0]: >14} | {time_06_build_output[1] - time_05_build_compats[1]: >13} |")
print(f"| write output  | {time_07_write_output[0] - time_06_build_output[0]: >14} | {time_07_write_output[1] - time_06_build_output[1]: >13} |")
print(f"| all           | {time_07_write_output[0] - time_00_start[0]: >14} | {time_07_write_output[1] - time_00_start[1]: >13} |")
