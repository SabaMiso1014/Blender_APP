#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright 2015 Blender Foundation - Bastien Montagne.


"""
This is a tool for generating a JSon version of a blender file (only its structure, or all its data included).

It can also run some simple validity checks over a .blend file.

WARNING! This is still WIP tool!

Example usage:

   ./blend2json.py foo.blend

To output also all 'name' fields from data:

   ./blend2json.py --filter-data="name" foo.blend

To output complete DNA struct info:

   ./blend2json.py --full-dna foo.blend

To avoid getting all 'uid' old addresses (those will change really often even when data itself does not change,
making diff pretty noisy):

   ./blend2json.py --no-old-addresses foo.blend

To check a .blend file instead of outputting its JSon version (use explicit -o option to do both at the same time):

   ./blend2json.py -c foo.blend

"""

FILTER_DOC = """
Each generic filter is made of three arguments, the include/exclude toggle ('+'/'-'), a regex to match against the name
of the field to check (either one of the 'meta-data' generated by json exporter, or actual data field from DNA structs),
and some regex to match against the data of this field (JSON-ified representation of the data, hence always a string).

Filters are evaluated in the order they are given, that is, if a block does not pass the first filter,
it is immediately rejected and no further check is done on it.

You can add some recursivity to a filter (that is, if an 'include' filter is successful over a 'pointer' property,
it will also automatically include pointed data, with a level of recursivity), by adding either
'*' (for infinite recursion) or a number (to specify the maximum level of recursion) to the include/exclude toggle.
Note that it only makes sense in 'include' case, and gets ignored for 'exclude' one.

Examples:

To include only MESH blocks:

   ./blend2json.py --filter-block "+" "code" "ME" foo.blend

To include only MESH or CURVE blocks and all data used by them:

   ./blend2json.py --filter-block "+" "code" "(ME)|(CU)" --filter-block "+*" ".*" ".*" foo.blend

"""

import os
import json
import re

# Avoid maintaining multiple blendfile modules
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "modules"))
del sys

import blendfile


##### Utils (own json formatting) #####


def json_default(o):
    if isinstance(o, bytes):
        return repr(o)[2:-1]
    elif i is ...:
        return "<...>"
    return o


def json_dumps(i):
    return json.dumps(i, default=json_default)


def keyval_to_json(kvs, indent, indent_step, compact_output=False):
    if compact_output:
        return ('{' + ', '.join('"%s": %s' % (k, v) for k, v in kvs) + '}')
    else:
        return ('{%s' % indent_step[:-1] +
                (',\n%s%s' % (indent, indent_step)).join(
                    ('"%s":\n%s%s%s' % (k, indent, indent_step, v) if (v[0] in {'[', '{'}) else
                     '"%s": %s' % (k, v)) for k, v in kvs) +
                '\n%s}' % indent)


def list_to_json(lst, indent, indent_step, compact_output=False):
    if compact_output:
        return ('[' + ', '.join(l for l in lst) + ']')
    else:
        return ('[%s' % indent_step[:-1] +
                ((',\n%s%s' % (indent, indent_step)).join(
                    ('\n%s%s%s' % (indent, indent_step, l) if (i == 0 and l[0] in {'[', '{'}) else l)
                    for i, l in enumerate(lst))
                 ) +
                '\n%s]' % indent)


##### Main 'struct' writers #####

def gen_fake_addresses(args, blend):
    if args.use_fake_address:
        hashes = set()
        ret = {}
        for block in blend.blocks:
            if not block.addr_old:
                continue
            hsh = block.get_data_hash()
            while hsh in hashes:
                hsh += 1
            hashes.add(hsh)
            ret[block.addr_old] = hsh
        return ret

    return {}


def bheader_to_json(args, fw, blend, indent, indent_step):
    fw('%s"%s": [\n' % (indent, "HEADER"))
    indent = indent + indent_step

    keyval = (
        ("magic", json_dumps(blend.header.magic)),
        ("pointer_size", json_dumps(blend.header.pointer_size)),
        ("is_little_endian", json_dumps(blend.header.is_little_endian)),
        ("version", json_dumps(blend.header.version)),
    )
    keyval = keyval_to_json(keyval, indent, indent_step)
    fw('%s%s' % (indent, keyval))

    indent = indent[:-len(indent_step)]
    fw('\n%s]' % indent)


def do_bblock_filter(filters, blend, block, meta_keyval, data_keyval):
    def do_bblock_filter_data_recursive(blend, block, rec_lvl, rec_iter, key=None):
        fields = (blend.structs[block.sdna_index].fields if key is None else
                  [blend.structs[block.sdna_index].field_from_name.get(key[1:-1].encode())])
        for fld in fields:
            if fld is None:
                continue
            if fld.dna_name.is_pointer:
                paths = ([(fld.dna_name.name_only, i) for i in range(fld.dna_name.array_size)]
                         if fld.dna_name.array_size > 1 else [fld.dna_name.name_only])
                for p in paths:
                    child_block = block.get_pointer(p)
                    if child_block is not None:
                        child_block.user_data = max(block.user_data, rec_iter)
                        if rec_lvl != 0:
                            do_bblock_filter_data_recursive(blend, child_block, rec_lvl - 1, rec_iter + 1)

    has_include = False
    do_break = False
    rec_iter = 1
    if block.user_data is None:
        block.user_data = 0
    for include, rec_lvl, key, val in filters:
        if rec_lvl < 0:
            rec_lvl = 100
        has_include = has_include or include
        # Skip exclude filters if block was already processed some way.
        if not include and block.user_data is not None:
            continue
        has_match = False
        for k, v in meta_keyval:
            if key.search(k) and val.search(v):
                has_match = True
                if include:
                    block.user_data = max(block.user_data, rec_iter)
                    # Note that in include cases, we have to keep checking filters, since some 'include recursive'
                    # ones may still have to be processed...
                else:
                    block.user_data = min(block.user_data, -rec_iter)
                    do_break = True  # No need to check more filters in exclude case...
                    break
        for k, v in data_keyval:
            if key.search(k) and val.search(v):
                has_match = True
                if include:
                    block.user_data = max(block.user_data, rec_iter)
                    if rec_lvl != 0:
                        do_bblock_filter_data_recursive(blend, block, rec_lvl - 1, rec_iter + 1, k)
                    # Note that in include cases, we have to keep checking filters, since some 'include recursive'
                    # ones may still have to be processed...
                else:
                    block.user_data = min(block.user_data, -rec_iter)
                    do_break = True  # No need to check more filters in exclude case...
                    break
        if include and not has_match:  # Include check failed, implies exclusion.
            block.user_data = min(block.user_data, -rec_iter)
            do_break = True  # No need to check more filters in exclude case...
        if do_break:
            break
    # Implicit 'include all' in case no include filter is specified...
    if block.user_data == 0 and not has_include:
        block.user_data = max(block.user_data, rec_iter)


def bblocks_to_json(args, fw, blend, address_map, indent, indent_step):
    no_address = args.no_address
    full_data = args.full_data
    filter_data = args.filter_data

    def gen_meta_keyval(blend, block):
        keyval = [
            ("code", json_dumps(block.code)),
            ("size", json_dumps(block.size)),
        ]
        if not no_address:
            keyval += [("addr_old", json_dumps(address_map.get(block.addr_old, block.addr_old)))]
        keyval += [
            ("dna_type_id", json_dumps(blend.structs[block.sdna_index].dna_type_id)),
            ("count", json_dumps(block.count)),
        ]
        return keyval

    def gen_data_keyval(blend, block, key_filter=None):
        def _is_pointer(k):
            return blend.structs[block.sdna_index].field_from_path(blend.header, blend.handle, k).dna_name.is_pointer
        if key_filter is not None:
            return [(json_dumps(k)[1:-1], json_dumps(address_map.get(v, v) if _is_pointer(k) else v))
                    for k, v in block.items_recursive_iter() if k in key_filter]
        return [(json_dumps(k)[1:-1], json_dumps(address_map.get(v, v) if _is_pointer(k) else v))
                for k, v in block.items_recursive_iter()]

    if args.block_filters:
        for block in blend.blocks:
            meta_keyval = gen_meta_keyval(blend, block)
            data_keyval = gen_data_keyval(blend, block)
            do_bblock_filter(args.block_filters, blend, block, meta_keyval, data_keyval)

    fw('%s"%s": [\n' % (indent, "DATA"))
    indent = indent + indent_step

    is_first = True
    for i, block in enumerate(blend.blocks):
        if block.user_data is None or block.user_data > 0:
            meta_keyval = gen_meta_keyval(blend, block)
            if full_data:
                meta_keyval.append(("data", keyval_to_json(gen_data_keyval(blend, block),
                                                           indent + indent_step, indent_step, args.compact_output)))
            elif filter_data:
                meta_keyval.append(("data", keyval_to_json(gen_data_keyval(blend, block, filter_data),
                                                           indent + indent_step, indent_step, args.compact_output)))
            keyval = keyval_to_json(meta_keyval, indent, indent_step, args.compact_output)
            fw('%s%s%s' % ('' if is_first else ',\n', indent, keyval))
            is_first = False

    indent = indent[:-len(indent_step)]
    fw('\n%s]' % indent)


def bdna_to_json(args, fw, blend, indent, indent_step):
    full_dna = args.full_dna and not args.compact_output

    def bdna_fields_to_json(blend, dna, indent, indent_step):
        lst = []
        for i, field in enumerate(dna.fields):
            keyval = (
                ("dna_name", json_dumps(field.dna_name.name_only)),
                ("dna_type_id", json_dumps(field.dna_type.dna_type_id)),
                ("is_pointer", json_dumps(field.dna_name.is_pointer)),
                ("is_method_pointer", json_dumps(field.dna_name.is_method_pointer)),
                ("array_size", json_dumps(field.dna_name.array_size)),
            )
            lst.append(keyval_to_json(keyval, indent + indent_step, indent_step))
        return list_to_json(lst, indent, indent_step)

    fw('%s"%s": [\n' % (indent, "DNA_STRUCT"))
    indent = indent + indent_step

    is_first = True
    for dna in blend.structs:
        keyval = [
            ("dna_type_id", json_dumps(dna.dna_type_id)),
            ("size", json_dumps(dna.size)),
        ]
        if full_dna:
            keyval += [("fields", bdna_fields_to_json(blend, dna, indent + indent_step, indent_step))]
        else:
            keyval += [("nbr_fields", json_dumps(len(dna.fields)))]
        keyval = keyval_to_json(keyval, indent, indent_step, args.compact_output)
        fw('%s%s%s' % ('' if is_first else ',\n', indent, keyval))
        is_first = False

    indent = indent[:-len(indent_step)]
    fw('\n%s]' % indent)


def blend_to_json(args, f, blend, address_map):
    fw = f.write
    fw('{\n')
    indent = indent_step = "  "
    bheader_to_json(args, fw, blend, indent, indent_step)
    fw(',\n')
    bblocks_to_json(args, fw, blend, address_map, indent, indent_step)
    fw(',\n')
    bdna_to_json(args, fw, blend, indent, indent_step)
    fw('\n}\n')


##### Checks #####

def check_file(args, blend):
    addr_old = set()
    for block in blend.blocks:
        if block.addr_old in addr_old:
            print("ERROR! Several data blocks share same 'addr_old' uuid %d, "
                  "this should never happen!" % block.addr_old)
            continue
        addr_old.add(block.addr_old)


##### Main #####

def argparse_create():
    import argparse
    global __doc__

    # When --help or no args are given, print this help
    usage_text = __doc__

    epilog = "This script is typically used to check differences between .blend files, or to check their validity."

    parser = argparse.ArgumentParser(description=usage_text, epilog=epilog,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument(
        dest="input", nargs="+", metavar='PATH',
        help="Input .blend file(s)")
    parser.add_argument(
        "-o", "--output", dest="output", action="append", metavar='PATH', required=False,
        help="Output .json file(s) (same path/name as input file(s) if not specified)")
    parser.add_argument(
        "-c", "--check-file", dest="check_file", default=False, action='store_true', required=False,
        help=("Perform some basic validation checks over the .blend file"))
    parser.add_argument(
        "--compact-output", dest="compact_output", default=False, action='store_true', required=False,
        help=("Output a very compact representation of blendfile (one line per block/DNAStruct)"))
    parser.add_argument(
        "--no-old-addresses", dest="no_address", default=False, action='store_true', required=False,
        help=("Do not output old memory address of each block of data "
              "(used as 'uuid' in .blend files, but change pretty noisily)"))
    parser.add_argument(
        "--no-fake-old-addresses", dest="use_fake_address", default=True, action='store_false',
        required=False,
        help=("Do not 'rewrite' old memory address of each block of data "
              "(they are rewritten by default to some hash of their content, "
              "to try to avoid too much diff noise between different but similar files)"))
    parser.add_argument(
        "--full-data", dest="full_data",
        default=False, action='store_true', required=False,
        help=("Also put in JSon file data itself "
              "(WARNING! will generate *huge* verbose files - and is far from complete yet)"))
    parser.add_argument(
        "--filter-data", dest="filter_data",
        default=None, required=False,
        help=("Only put in JSon file data fields which names match given comma-separated list "
              "(ignored if --full-data is set)"))
    parser.add_argument(
        "--full-dna", dest="full_dna", default=False, action='store_true', required=False,
        help=("Also put in JSon file dna properties description (ignored when --compact-output is used)"))

    group = parser.add_argument_group("Filters", FILTER_DOC)
    group.add_argument(
        "--filter-block", dest="block_filters", nargs=3, action='append',
        help=("Filter to apply to BLOCKS (a.k.a. data itself)"))

    return parser


def main():
    # ----------
    # Parse Args

    args = argparse_create().parse_args()

    if not args.output:
        if args.check_file:
            args.output = [None] * len(args.input)
        else:
            args.output = [os.path.splitext(infile)[0] + ".json" for infile in args.input]

    if args.block_filters:
        args.block_filters = [(True if m[0] == "+" else False,
                               0 if len(m) == 1 else (-1 if m[1] == "*" else int(m[1:])),
                               re.compile(f), re.compile(d))
                              for m, f, d in args.block_filters]

    if args.filter_data:
        if args.full_data:
            args.filter_data = None
        else:
            args.filter_data = {n.encode() for n in args.filter_data.split(',')}

    for infile, outfile in zip(args.input, args.output):
        with blendfile.open_blend(infile) as blend:
            address_map = gen_fake_addresses(args, blend)

            if args.check_file:
                check_file(args, blend)

            if outfile:
                with open(outfile, 'w', encoding="ascii", errors='xmlcharrefreplace') as f:
                    blend_to_json(args, f, blend, address_map)


if __name__ == "__main__":
    main()
