#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Author: Rico Sennrich

"""Use byte pair encoding (BPE) to learn a variable-length encoding of the vocabulary in a text.
This script learns BPE jointly on a concatenation of a list of texts (typically the source and target side of a parallel corpus,
applies the learned operation to each and (optionally) returns the resulting vocabulary of each text.
The vocabulary can be used in apply_bpe.py to avoid producing symbols that are rare or OOV in a training text.

Reference:
Rico Sennrich, Barry Haddow and Alexandra Birch (2016). Neural Machine Translation of Rare Words with Subword Units.
Proceedings of the 54th Annual Meeting of the Association for Computational Linguistics (ACL 2016). Berlin, Germany.
"""

from __future__ import unicode_literals

import sys
import os
import inspect
import codecs
import argparse
import tempfile
import warnings
from collections import Counter

#hack to get imports working if running this as a script, or within a package
if __name__ == '__main__':
    import learn_bpe
    import apply_bpe
else:
    from . import learn_bpe
    from . import apply_bpe

# hack for python2/3 compatibility
from io import open
argparse.open = open

def create_parser(subparsers=None):

    if subparsers:
        parser = subparsers.add_parser('learn-joint-bpe-and-vocab',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description="learn BPE-based word segmentation")
    else:
        parser = argparse.ArgumentParser(
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description="learn BPE-based word segmentation")

    parser.add_argument(
        '--input', '-i', type=argparse.FileType('r'), required=True, nargs = '+',
        metavar='PATH',
        help="Input texts (multiple allowed).")
    parser.add_argument(
        '--output', '-o', type=argparse.FileType('w'), required=True,
        metavar='PATH',
        help="Output file for BPE codes.")
    parser.add_argument(
        '--symbols', '-s', type=int, default=10000,
        help="Create this many new symbols (each representing a character n-gram) (default: %(default)s)")
    parser.add_argument(
        '--special-vocab', help="Special vocab file, which should preferrably be unsegmented, unless symbols created already reaches --symbols limit")
    parser.add_argument(
        '--separator', type=str, default='@@', metavar='STR',
        help="Separator between non-final subword units (default: '%(default)s')")
    parser.add_argument(
        '--write-vocabulary', type=argparse.FileType('w'), required=True, nargs = '+', default=None,
        metavar='PATH', dest='vocab',
        help='Write to these vocabulary files after applying BPE. One per input text. Used for filtering in apply_bpe.py')
    parser.add_argument(
        '--min-frequency', type=int, default=2, metavar='FREQ',
        help='Stop if no symbol pair has frequency >= FREQ (default: %(default)s)')
    parser.add_argument('--dict-input', action="store_true",
        help="If set, input file is interpreted as a dictionary where each line contains a word-count pair")
    parser.add_argument('--postpend', action='store_true',
        help="Place subsequent subwords to the right of the first subword (default: prepend subwords to the left of the last subword)")
    parser.add_argument(
        '--total-symbols', '-t', action="store_true",
        help="subtract number of characters from the symbols to be generated (so that '--symbols' becomes an estimate for the total number of symbols needed to encode text).")
    parser.add_argument(
        '--character-vocab', '-c', action="store_true",
        help="include individual characters in the vocabulary")
    parser.add_argument(
        '--verbose', '-v', action="store_true",
        help="verbose mode.")

    return parser

def yield_dict_lines(d):
    it = d.iteritems() if sys.version_info < (3, 0) else d.items()
    for k, v in it:
        yield '{0} {1}'.format(k, v)

def learn_joint_bpe_and_vocab(args):

    if args.vocab and len(args.input) != len(args.vocab):
        sys.stderr.write('Error: number of input files and vocabulary files must match\n')
        sys.exit(1)

    # read/write files as UTF-8
    args.input = [codecs.open(f.name, encoding='UTF-8') for f in args.input]
    args.vocab = [codecs.open(f.name, 'w', encoding='UTF-8') for f in args.vocab]

    if args.special_vocab:
        with codecs.open(args.special_vocab, encoding='UTF-8') as f:
            l = [line.strip('\r\n ') for line in codecs.open(args.special_vocab, encoding='UTF-8')]
        args.special_vocab = l

    # get combined vocabulary of all input texts
    full_vocab = Counter()
    for f in args.input:
        full_vocab += learn_bpe.get_vocabulary(f, args.dict_input)
        f.seek(0)
    if args.special_vocab:
        for word in args.special_vocab:
            full_vocab[word] += 1  # integrate special vocab to full_vocab

    vocab_list = yield_dict_lines(full_vocab)

    # learn BPE on combined vocabulary
    with codecs.open(args.output.name, 'w', encoding='UTF-8') as output:
        learn_bpe.learn_bpe(vocab_list, output, args.symbols, args.min_frequency, args.verbose, is_dict=True, total_symbols=args.total_symbols, is_postpend=args.postpend, special_vocab=args.special_vocab)

    with codecs.open(args.output.name, encoding='UTF-8') as codes:
        bpe = apply_bpe.BPE(codes, separator=args.separator, is_postpend=args.postpend)

    # apply BPE to each training corpus and get vocabulary
    for train_file, vocab_file in zip(args.input, args.vocab):
        if args.dict_input:
            vocab = Counter()
            for i, line in enumerate(train_file):
                try:
                    word, count = line.strip('\r\n ').split(' ')
                    segments = bpe.segment_tokens([word])
                except:
                    print('Failed reading vocabulary file at line {0}: {1}'.format(i, line))
                    sys.exit(1)
                for seg in segments:
                    vocab[seg] += int(count)
        else:
            tmp = tempfile.NamedTemporaryFile(delete=False)
            tmp.close()

            tmpout = codecs.open(tmp.name, 'w', encoding='UTF-8')

            train_file.seek(0)
            for line in train_file:
                tmpout.write(bpe.process_line(line).strip())
                tmpout.write('\n')

            tmpout.close()
            tmpin = codecs.open(tmp.name, encoding='UTF-8')

            vocab = learn_bpe.get_vocabulary(tmpin)
            tmpin.close()
            os.remove(tmp.name)
        
        # if special vocab is defined, include them
        if args.special_vocab:
            for i, word in enumerate(args.special_vocab):
                try:
                    segments = bpe.segment_tokens([word])
                except:
                    print('Failed reading special vocabulary file at line {0}: {1}'.format(i, line))
                    sys.exit(1)
                if len(segments) != 1:
                    sys.stderr.write('WARNING: special vocab \'{0}\' not captured by merges, split into \'{1}\'\n'.format(word, ' '.join(segments)))
                for seg in segments:
                    vocab[seg] += 1
        
        sys.stderr.write('Vocabulary got {0:d} unique items\n'.format(len(vocab)))

        # if character vocab is to be included
        if args.character_vocab:
            char_internal, char_terminal = learn_bpe.extract_uniq_chars(full_vocab, args.postpend)
            sys.stderr.write('Got {0:d} non-terminal and {1:d} terminal characters\n'.format(len(char_internal), len(char_terminal)))
            pseudo_count_terminal = max(vocab.values()) + 2 # always precedes non-terminal
            pseudo_count_internal = max(vocab.values()) + 1 # always precedes other items
            for c in char_terminal:
                vocab[c] = pseudo_count_terminal
            for c in char_internal:
                c = '{0}{1}'.format(args.separator, c) if args.postpend else '{0}{1}'.format(c, args.separator)
                vocab[c] = pseudo_count_internal
        for key, freq in sorted(vocab.items(), key=lambda x: (-x[1], x[0])):
            vocab_file.write("{0} {1}\n".format(key, freq))
        train_file.close()
        vocab_file.close()


if __name__ == '__main__':

    currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
    newdir = os.path.join(currentdir, 'subword_nmt')
    if os.path.isdir(newdir):
        warnings.simplefilter('default')
        warnings.warn(
            "this script's location has moved to {0}. This symbolic link will be removed in a future version. Please point to the new location, or install the package and use the command 'subword-nmt'".format(newdir),
            DeprecationWarning
        )

    # python 2/3 compatibility
    if sys.version_info < (3, 0):
        sys.stderr = codecs.getwriter('UTF-8')(sys.stderr)
        sys.stdout = codecs.getwriter('UTF-8')(sys.stdout)
        sys.stdin = codecs.getreader('UTF-8')(sys.stdin)
    else:
        sys.stderr = codecs.getwriter('UTF-8')(sys.stderr.buffer)
        sys.stdout = codecs.getwriter('UTF-8')(sys.stdout.buffer)
        sys.stdin = codecs.getreader('UTF-8')(sys.stdin.buffer)

    parser = create_parser()
    args = parser.parse_args()

    if sys.version_info < (3, 0):
        args.separator = args.separator.decode('UTF-8')

    assert(len(args.input) == len(args.vocab))

    learn_joint_bpe_and_vocab(args)
