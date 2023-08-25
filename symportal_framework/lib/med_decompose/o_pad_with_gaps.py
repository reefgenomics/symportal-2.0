#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (C) 2010 - 2012, A. Murat Eren
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# Please read the COPYING file.

import sys

import Oligotyping.lib.fastalib as u


def main(input_fasta_path, output_fasta_path=None, reverse=False):
    if not output_fasta_path:
        output_fasta_path = input_fasta_path + '-PADDED-WITH-GAPS'

    fasta = u.SequenceSource(input_fasta_path)
    output = u.FastaOutput(output_fasta_path)

    longest_read = 0
    while next(fasta):
        if len(fasta.seq) > longest_read:
            longest_read = len(fasta.seq)
    
    fasta.reset()
    
    while next(fasta):
        if fasta.pos % 10000 == 0:
            sys.stderr.write('\rreads processed so far: %d' % (fasta.pos))
            sys.stderr.flush()
    
        gaps = longest_read - len(fasta.seq)
        
        output.write_id(fasta.id)
        if reverse:
            output.write_seq('-' * gaps + fasta.seq, split = False)
        else:
            output.write_seq(fasta.seq + '-' * gaps, split = False)
    
    
    fasta.close()
    sys.stderr.write('\n')

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Pad sequences with gaps to eliminate length variation')
    parser.add_argument('fasta', metavar = 'FASTA_FILE_PATH',
                        help = 'FASTA file that contains reads to be padded')
    parser.add_argument('--reverse', action = 'store_true', default = False,
                        help = 'Pad the beginning of reads, instead of the end (default: %(default)s)')
    parser.add_argument('-o', '--output', metavar = 'FILE_FILE_PATH', default = None,
                        help = 'Path for output.')


    args = parser.parse_args()

    main(args.fasta, args.output, args.reverse)

    sys.exit()
