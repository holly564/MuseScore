#!/usr/bin/env python3

"""usage: ./gen-ucd-table ucd.nounihan.grouped.xml [/path/to/hb-common.h]

Input file:
* https://unicode.org/Public/UCD/latest/ucdxml/ucd.nounihan.grouped.zip
"""

import sys, re
import logging
logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)

if len (sys.argv) not in (2, 3):
	sys.exit (__doc__)

# https://github.com/harfbuzz/packtab
import packTab
import packTab.ucdxml

logging.info('Loading UCDXML...')
ucdxml = packTab.ucdxml.load_ucdxml(sys.argv[1])
ucd = packTab.ucdxml.ucdxml_get_repertoire(ucdxml)

hb_common_h = 'hb-common.h' if len (sys.argv) < 3 else sys.argv[2]

logging.info('Preparing data tables...')


# This is how the data is encoded:
#
# General_Category (gc), Canonical_Combining_Class (ccc),
# and Script (sc) are encoded as integers.
#
# Mirroring character (bmg) is encoded as difference from
# the original character.
#
# Composition & Decomposition (dm) are encoded elaborately,
# as discussed below.

gc = [u['gc'] for u in ucd]
ccc = [int(u['ccc']) for u in ucd]
bmg = [int(v, 16) - int(u) if v else 0 for u,v in enumerate(u['bmg'] for u in ucd)]
sc = [u['sc'] for u in ucd]


# Prepare Compose / Decompose data
#
# This code is very dense.  See hb_ucd_compose() / hb_ucd_decompose() for the logic.

dm = {i:tuple(int(v, 16) for v in u['dm'].split()) for i,u in enumerate(ucd)
      if u['dm'] != '#' and u['dt'] == 'can' and not (0xAC00 <= i < 0xAC00+11172)}
ce = {i for i,u in enumerate(ucd) if u['Comp_Ex'] == 'Y'}

assert not any(v for v in dm.values() if len(v) not in (1,2))
dm1 = sorted(set(v for v in dm.values() if len(v) == 1))
assert all((v[0] >> 16) in (0,2) for v in dm1)
dm1_p0_array = ['0x%04Xu' % (v[0] & 0xFFFF) for v in dm1 if (v[0] >> 16) == 0]
dm1_p2_array = ['0x%04Xu' % (v[0] & 0xFFFF) for v in dm1 if (v[0] >> 16) == 2]
dm1_order = {v:i+1 for i,v in enumerate(dm1)}

dm2 = sorted((v+(i if i not in ce and not ccc[i] else 0,), v)
             for i,v in dm.items() if len(v) == 2)

filt = lambda v: ((v[0] & 0xFFFFF800) == 0x0000 and
                  (v[1] & 0xFFFFFF80) == 0x0300 and
                  (v[2] & 0xFFF0C000) == 0x0000)
dm2_u32_array = [v for v in dm2 if filt(v[0])]
dm2_u64_array = [v for v in dm2 if not filt(v[0])]
assert dm2_u32_array + dm2_u64_array == dm2
dm2_u32_array = ["HB_CODEPOINT_ENCODE3_11_7_14 (0x%04Xu, 0x%04Xu, 0x%04Xu)" % v[0] for v in dm2_u32_array]
dm2_u64_array = ["HB_CODEPOINT_ENCODE3 (0x%04Xu, 0x%04Xu, 0x%04Xu)" % v[0] for v in dm2_u64_array]

l = 1 + len(dm1_p0_array) + len(dm1_p2_array)
dm2_order = {v[1]:i+l for i,v in enumerate(dm2)}

dm_order = {None: 0}
dm_order.update(dm1_order)
dm_order.update(dm2_order)


# Prepare General_Category / Script mapping arrays

gc_order = dict()
for i,v in enumerate(('Cc', 'Cf', 'Cn', 'Co', 'Cs', 'Ll', 'Lm', 'Lo', 'Lt', 'Lu',
                      'Mc', 'Me', 'Mn', 'Nd', 'Nl', 'No', 'Pc', 'Pd', 'Pe', 'Pf',
                      'Pi', 'Po', 'Ps', 'Sc', 'Sk', 'Sm', 'So', 'Zl', 'Zp', 'Zs',)):
    gc_order[i] = v
    gc_order[v] = i

sc_order = dict()
sc_array = []
sc_re = re.compile(r"\b(HB_SCRIPT_[_A-Z]*).*HB_TAG [(]'(.)','(.)','(.)','(.)'[)]")
for line in open(hb_common_h):
    m = sc_re.search (line)
    if not m: continue
    name = m.group(1)
    tag = ''.join(m.group(i) for i in range(2, 6))
    i = len(sc_array)
    sc_order[tag] = i
    sc_order[i] = tag
    sc_array.append(name)


# Write out main data

DEFAULT = 'DEFAULT'
COMPACT = 'COMPACT'
SLOPPY  = 'SLOPPY'

compression_level = {
    DEFAULT: 5,
    COMPACT: 9,
    SLOPPY:  9,
}

logging.info('Generating output...')
print("/* == Start of generated table == */")
print("/*")
print(" * The following table is generated by running:")
print(" *")
print(" *   ./gen-ucd-table.py ucd.nounihan.grouped.xml")
print(" *")
print(" * on file with this description:", ucdxml.description)
print(" */")
print()
print("#ifndef HB_UCD_TABLE_HH")
print("#define HB_UCD_TABLE_HH")
print()
print('#include "hb.hh"')
print()


# Write mapping data

code = packTab.Code('_hb_ucd')
sc_array, _ = code.addArray('hb_script_t', 'sc_map', sc_array)
dm1_p0_array, _ = code.addArray('uint16_t', 'dm1_p0_map', dm1_p0_array)
dm1_p2_array, _ = code.addArray('uint16_t', 'dm1_p2_map', dm1_p2_array)
dm2_u32_array, _ = code.addArray('uint32_t', 'dm2_u32_map', dm2_u32_array)
dm2_u64_array, _ = code.addArray('uint64_t', 'dm2_u64_map', dm2_u64_array)
code.print_c(linkage='static inline')

datasets = [
    ('gc', gc, 'Cn', gc_order),
    ('ccc', ccc, 0, None),
    ('bmg', bmg, 0, None),
    ('sc', sc, 'Zzzz', sc_order),
    ('dm', dm, None, dm_order),
]


# Write main data

for step in (DEFAULT, COMPACT, SLOPPY):
    compression = compression_level[step]
    logging.info('  Compression=%d:' % compression)
    print()
    if step == DEFAULT:
        print('#ifndef HB_OPTIMIZE_SIZE')
    elif step == COMPACT:
        print('#elif !defined(HB_NO_UCD_UNASSIGNED)')
    elif step == SLOPPY:
        print('#else')
    else:
        assert False
    print()

    if step == SLOPPY:
        for i in range(len(gc)):
            if (i % 128) and gc[i] == 'Cn':
                gc[i] = gc[i - 1]
        for i in range(len(gc) - 2, -1, -1):
            if ((i + 1) % 128) and gc[i] == 'Cn':
                gc[i] = gc[i + 1]
        for i in range(len(sc)):
            if (i % 128) and sc[i] == 'Zzzz':
                sc[i] = sc[i - 1]
        for i in range(len(sc) - 2, -1, -1):
            if ((i + 1) % 128) and sc[i] == 'Zzzz':
                sc[i] = sc[i + 1]


    code = packTab.Code('_hb_ucd')

    for name,data,default,mapping in datasets:
        sol = packTab.pack_table(data, default, mapping=mapping, compression=compression)
        logging.info('      Dataset=%-8s FullCost=%d' % (name, sol.fullCost))
        sol.genCode(code, name)

    code.print_c(linkage='static inline')

    print()


print('#endif')
print()

print()
print("#endif /* HB_UCD_TABLE_HH */")
print()
print("/* == End of generated table == */")
logging.info('Done.')
