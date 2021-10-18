#!/usr/bin/env python
import argparse
import math
import sys

parser = argparse.ArgumentParser(description="", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument("infile",  help="input bam file") #,  type=argparse.FileType('r'), default=sys.stdin)
parser.add_argument("outfile",  help="output plot file")
parser.add_argument('-d', action="store_true", default=False)
parser.add_argument('--legend', action="store_true", default=False)
parser.add_argument('--zerostart', action="store_true", default=False)
parser.add_argument('-a', help="output all positions", action="store_true", default=False)
parser.add_argument('-r', '--repeatmasker', help="rm out to add to plot", type=argparse.FileType('r') , default=None)
parser.add_argument('--regions', nargs='*', help='regions in this format (.*):(\d+)-(\d+)')
parser.add_argument('--bed', default=None, help="bed file with regions to plot")
parser.add_argument('--obed', default=None, help="output a bed with the data points")
parser.add_argument('--minobed', help="min number of discordant bases to report in obed", type=int , default=2)
parser.add_argument('-y', '--ylim', help="max y axis limit", type=float , default=None)
parser.add_argument('-f', '--font-size', help="plot font-size", type=int , default=16)
parser.add_argument('--freey', action="store_true", default=False)
parser.add_argument('--height', help="figure height", type=float , default=9)
parser.add_argument('-w', '--width', help="figure width", type=float , default=16)
parser.add_argument('--dpi', help="dpi for png", type=float , default=600)
parser.add_argument('-t', '--threads', help="[8]", type=int , default=8)
parser.add_argument('--header', action="store_true", default=False)
parser.add_argument('--no-title', action="store_true", default=False)
parser.add_argument('--no-xlabel', action="store_true", default=False)
parser.add_argument("--psvsites", help="CC/mi.gml.sites", default=None)
parser.add_argument('-s', '--soft', action="store_true", default=False)
parser.add_argument('-c', '--minclip', help="min number of clippsed bases in order to be displayed", type=float , default=1000)
parser.add_argument('-n', '--name', help="name of tech to put in y axis", default=None)
args = parser.parse_args()

sys.stderr.write(f"Using a font-size of {args.font_size}\n")

print("Beginning load", file=sys.stderr, flush=True)
import os 
import numpy as np
import pysam
import re
import pandas as pd
import matplotlib
matplotlib.use('agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import seaborn as sns 
from multiprocessing import Pool

M=0 #M  BAM_CMATCH      0
I=1 #I  BAM_CINS        1
D=2 #D  BAM_CDEL        2
N=3 #N  BAM_CREF_SKIP   3
S=4 #S  BAM_CSOFT_CLIP  4
H=5 #H  BAM_CHARD_CLIP  5
P=6 #P  BAM_CPAD        6
E=7 #=  BAM_CEQUAL      7
X=8 #X  BAM_CDIFF       8
B=9 #B  BAM_CBACK       9
NM=10 #NM       NM tag  10
conRef  =       [M, D, N, E, X] # these ones "consume" the reference
conQuery=       [M, I, S, E, X] # these ones "consume" the query
conAln  =       [M, I, D, N, S, E, X] # these ones "consume" the alignments


print("Packages loaded", file=sys.stderr, flush=True)


def getSoft(read, group=0):
  rtn = []
  cigar = read.cigartuples
  start = cigar[0]
  end = cigar[-1]
  if(start[0] in [S,H]):
    rtn.append( (read.reference_name, "start", start[1], read.reference_start, read, group) )
  if(end[0] in [S,H] ):
    rtn.append( (read.reference_name, "end", end[1], read.reference_end, read, group) )
  return(rtn)


soft = []
bam = pysam.AlignmentFile(args.infile)
refs = {}
regions = []
if(args.regions is not None or args.bed is not None):
    print("Reading in the region or bed argument(s).", file=sys.stderr, flush=True)
    if(args.regions is not None):
        for region in args.regions:
            match = re.match("(.+):(\d+)-(\d+)", region)
            assert match, region + " not valid!"
            chrm , start, end = match.groups()
            refs[chrm] = [int(start), int(end)]
            regions.append( (chrm, int(start), int(end)) ) 

    if(args.bed is not None):
        for line in open(args.bed):
            line = line.strip().split()
            chrm, start, end = line[0:3]
            refs[chrm] = [int(start), int(end)]
            regions.append( (chrm, int(start), int(end)) ) 

else:
  print("Reading the whole bam becuase no region or bed argument was made.", file=sys.stderr, flush=True)
  for read in bam.fetch(until_eof=True):
    ref = read.reference_name
    #read.query_qualities = [60] * len(read.query_sequence) 
    soft += getSoft(read)
    if(ref not in refs):
      if(args.a):
        refs[ref] = [0, 2147483648]
      else:
        refs[ref] = [2147483648, 0]
    
    start = read.reference_start
    end = read.reference_end
    if(refs[ref][0] > start ):
      refs[ref][0]=start
    if(refs[ref][1] < end ):
      refs[ref][1]=end
  for contig in refs:
    regions.append((contig, refs[contig][0], refs[contig][1])) 


def getCovByBase(contig, start, end):
    #coverage = bam.count_coverage(contig, quality_threshold=None, start=start, stop=end, read_callback="nofilter")
    #sys.stderr.write(f"{contig},{start},{end}\n")
    coverage = bam.count_coverage(contig,  start=start, stop=end, read_callback="nofilter", quality_threshold=None)
    assert len(coverage) == 4
    cov = {}
    cov["A"] = coverage[0]
    cov["C"] = coverage[1]
    cov["T"] = coverage[2]
    cov["G"] = coverage[3]
    return(cov)


#
# creates a table of nucleotide frequescies 
#
#nf = []
nf = {"contig":[], "position":[], "A":[], "C":[], "G":[], "T":[], "group":[]}
GROUPS = 0
for contig, start, end  in regions:
    #start, end = refs[contig]
    print("Reading in NucFreq from region: {}:{}-{}".format(contig,start,end), file=sys.stderr, flush=True)
    cov = getCovByBase(contig, start, end)
    contiglen = len(cov["A"])
    if(contiglen > 0):
        #for i in range(contiglen):
        #  nf.append( [contig, start + i, cov["A"][i], cov["C"][i], cov["G"][i], cov["T"][i] ]   )
        nf["contig"]+=[contig]*contiglen 
        nf["group"] +=[GROUPS]*contiglen
        nf["position"]+=list(range(start, start+contiglen))
        nf["A"] += cov["A"]; nf["C"] += cov["C"]; nf["G"] += cov["G"]; nf["T"] += cov["T"]
        if(args.soft):
            for read in bam.fetch(contig,start,end):
                soft += getSoft(read, group=GROUPS)
        GROUPS += 1
            
  
#df = pd.DataFrame(nf, columns=["contig", "position", "A", "C", "G", "T"])
df = pd.DataFrame(nf)
sort = np.flip( np.sort(df[["A","C","G","T"]].values) , 1)
df["first"] = sort[:,0]
df["second"] = sort[:,1]
df["third"] = sort[:,2]
df["fourth"] = sort[:,3]
df.sort_values(by=["contig", "position", "second"], inplace=True)


soft = pd.DataFrame(soft, columns=["contig", "side", "value", "position", "read","group"])
#print(len(soft), file=sys.stderr)
soft = soft[soft.value >= args.minclip]
#print(len(soft), file=sys.stderr)
soft.sort_values(by=["contig", "position"], inplace=True)



RM=None
colors = sns.color_palette()
cmap = {}
counter = 0
if(args.repeatmasker is not None):
  print("Reading repeat masker input", file=sys.stderr, flush=True)

  names = ["qname", "start", "end", "family", "score", "strand", "other1", "other2", "color"]
  lines = []
  for idx, line in enumerate(args.repeatmasker):
    if(idx > 2):
      l = line.strip().split()
      l[8] = '#' + ''.join('{:02x}'.format(int(i)) for i in l[8].split(","))
      lines.append(l)
  
  RM = pd.DataFrame(lines, columns=names)
  RM.start = RM.start.astype(int)
  RM.end = RM.end.astype(int)
  #RM["label"] =RM.family.str.replace("/.*", "")
  #for idx, lab in enumerate(sorted(RM.label.unique())):
  #  cmap[lab] = colors[ counter%len(colors) ]
  #  counter += 1
  #  print("Set label %s to color %s"%(lab, cmap[lab]), file=sys.stderr, flush=True)
  #RM["color"] = RM.label.map(cmap)
  
  args.repeatmasker.close()
  print("Done reading RM", file=sys.stderr, flush=True)

print("Plotting {} regions in {}".format(GROUPS, args.outfile), file=sys.stderr, flush=True)
# SET up the plot based on the number of regions 
HEIGHT=GROUPS*args.height
# set text size
matplotlib.rcParams.update({'font.size': args.font_size})
# make axes 
fig, axs = plt.subplots(nrows=GROUPS, ncols=1, figsize=(args.width, HEIGHT) )
if(GROUPS==1): axs = [axs]
# make space for the bottom label of the plot
#fig.subplots_adjust(bottom=0.2)
# set figure YLIM
YLIM = int(max(df["first"])*1.05)

# iterate over regions
counter = 0
for group_id, group in df.groupby(by="group"):
    if(args.freey):
        YLIM = int(max(group["first"])*1.05)
        
    contig = list(group.contig)[0]

    truepos = group.position.values
    first = group["first"].values
    second = group["second"].values
    print("Plotting truepos:", file=sys.stderr, flush=True)
    print(truepos, file=sys.stderr, flush=True)
    print(first, file=sys.stderr, flush=True)
    print(second, file=sys.stderr, flush=True)
    
    #df = pd.DataFrame(nf, columns=["contig", "position", "A", "C", "G", "T"])
    if args.obed:
        tmp = group.loc[group.second >= args.minobed, ["contig","position","position","first","second"]]
        if counter == 0:
            tmp.to_csv(args.obed, header=["#contig","start","end","first","second"],
                       sep="\t", index=False)
        else:
            tmp.to_csv(args.obed, mode="a", header=None,
                       sep="\t", index=False)





    # get the correct axis 
    ax = axs[group_id]

    if(args.ylim is not None):
        ax.set_ylim(0, args.ylim)
        YLIM = args.ylim
    else:
        ax.set_ylim(0, YLIM)

    if(RM is not None):
        rmax = ax
        print("Trying to get RM for contig %s with psitions %d-%d"%(contig, min(truepos), max(truepos)), file=sys.stderr, flush=True)
        rm = RM[ (RM.qname == contig) & (RM.start >= min(truepos)) & (RM.end <= max(truepos)) ]
        print("Done searching for RM found %d entries"%(len(rm.index)), file=sys.stderr, flush=True)
        assert len(rm.index) != 0, "No matching RM contig"
        #rmax.set_xlim(rm.start.min(), rm.end.max())
        #rmax.set_ylim(-1, 9)

        counter = 0
        for idx, row in rm.iterrows():  
            if (counter % 100 == 0):
               print("Loaded %d RM entries for region %d-%d color %s"%(idx, row.start, row.end, row.color), file=sys.stderr, flush=True)
            counter = counter + 1
            width = row.end - row.start
            rect = patches.Rectangle((row.start,min(YLIM, args.ylim)-5), width, 5, linewidth=1, edgecolor='none',facecolor=row.color, alpha = .75) 
            rmax.add_patch(rect)
        plt.show()

    prime, = ax.plot(truepos, first, 'o', color="black", markeredgewidth=0.0, markersize=2, label = "most frequent base pair")
    sec, = ax.plot(truepos, second,'o', color="red",   markeredgewidth=0.0, markersize=4, label = "second most frequent base pair")


    #inter = int( (max(truepos)-min(truepos))/50)
    #sns.lineplot(  (truepos/inter).astype(int)*inter, first, ax = ax, err_style="bars") 


    maxval = max(truepos)
    minval = min(truepos)
    subval = 0

    if args.no_title:
        print("Not setting a title", file=sys.stderr, flush=True)
    else:
        title = "{}:{}-{}\n".format(contig, minval, maxval)
        #if(GROUPS > 1):
        ax.set_title(title, fontweight='bold', fontsize=args.font_size + 2)
        print(title, file=sys.stderr, flush=True)

    if(args.zerostart):
        print(ax.get_xticks(), file=sys.stderr, flush=True)
        #subval = ax.get_xticks()[0]
        #if ax.get_xticks()[0] < 0:
        #   subval=ax.get_xticks()[1]

        # original code 
        subval = minval - 1 
        ax.set_xticks(  [ x for x in ax.get_xticks() if (x - subval > 0) and (x < maxval)  ] )
        maxval = maxval - minval 
        print(ax.get_xticks(), file=sys.stderr, flush=True)
    if( maxval < 1000000 ):
        xlabels = [format( (label-subval), ',.0f') for label in ax.get_xticks()]
        lab = "bp"
    #elif( maxval < 10000000):
    #    xlabels = [format( (label-subval)/1000, ',.1f') for label in ax.get_xticks()]
    #    lab = "kbp"
    else:
        #xlabels = [format( (label-subval)/1000, ',.1f') for label in ax.get_xticks()]
        #lab = "kbp"
        xlabels = [ format((label-subval)/1000000, ',.1f') for label in ax.get_xticks()]
        lab = "Mbp"


    if not args.no_xlabel:
        #ax.set_xlabel('Assembly position ({})'.format(lab), fontweight='bold')
        ax.set_xlabel("{}:{}-{}\n".format(contig, minval, maxval), fontweight='bold')

    if args.name is not None:
        ax.set_ylabel('{} depth'.format(args.name), fontweight='bold')

    #ax.set_xticklabels(xlabels)
    ax.set_xticklabels([])
    ax.set_yticklabels([])

    # Hide the right and top spines
    ax.spines["right"].set_visible(False)
    ax.spines["top"].set_visible(False)
    # Only show ticks on the left and bottom spines
    ax.yaxis.set_ticks_position('left')
    ax.xaxis.set_ticks_position('bottom')

    if(counter == 0 and args.legend):
        lgnd = plt.legend(loc="upper right")
        for handle in lgnd.legendHandles:
            handle._sizes = ([300.0])

    if(args.soft ):
        tmpsoft = soft[ soft.group == group_id ]
        if(len(tmpsoft) > 0 ):
            axsoft = ax.twinx()
            axsoft.invert_yaxis()
            bins = args.width * 5
            color = "darkgreen"
            sns.distplot(tmpsoft.position, bins=bins, kde=False, ax=axsoft, hist_kws={'weights': tmpsoft.value/1000, "alpha": .25, "color": color})
            bot, top = axsoft.get_ylim()
            axsoft.set_ylim(1.1*bot, 0)
            axsoft.set_xlim(minval, maxval)
            # Hide the right and top spines
            axsoft.spines["top"].set_visible(False)
            # Only show ticks on the left and bottom spines
            axsoft.yaxis.set_ticks_position('right')
            #axsoft.xaxis.set_ticks_position('bottom')
            axsoft.tick_params(axis='y', colors=color)
            axsoft.set_ylabel('Clipped Bases (kbp)', color=color)


    if(args.psvsites is not None): #and len(args.psvsites)>0):
        cuts = {}
        for idx, line in enumerate(open(args.psvsites).readlines()):
            try:  
                vals = line.strip().split()
                cuts[idx] = list(map(int, vals))
                #make plot
                x = np.array(cuts[idx]) -1
                idxs = (np.isin(truepos, x))
                y = second[ idxs ]
                ax.plot(x,y, alpha=0.5) #, label="group:{}".format(idx) )
            except Exception as e:
                print("Skipping because error: {}".format(e), file=sys.stderr, flush=True)
                continue

    #outpath = os.path.abspath(args.outfile)
    #if(counter == 0):
    #  outf =   outpath
    #else:
    #  name, ext = os.path.splitext(outpath) 
    #  outf = "{}_{}{}".format(name, counter + 1, ext)

    counter += 1

plt.tight_layout()
plt.savefig(args.outfile, transparent=True, dpi=args.dpi, format="png")
