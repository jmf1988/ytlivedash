#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from concurrent.futures import ThreadPoolExecutor
from threading import active_count as active_threads
try:
    import xml.etree.cElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse
import requests
import logging
import os
import signal
import sys
import time
import subprocess
import re
import shlex
import json
import argparse
try:
    import gtk
    maxwidth = gtk.gdk.screen_width()
    maxheight = gtk.gdk.screen_height()
except ImportError:
    pass


class Ended(Exception):
    pass


def log_(infos):
    logging.debug('''---> Going %s, to VID: %s
                 REMAINING SEGMENTS: %s
                 MIN DELAY: %s
                 FFMUX DELAY: %s
                 DELAY TO UP: %s
                 TRUE DELAYS: %s
                 TRUE DELAY AVG: %s
                 BASE DELAYS: %s
                 BASE DELAY AVG: %s
                 DELAYS: %s
                 DELAY AVG: %s
                 CURRENT BAND: %s
                 NEXT BAND: %s
                 MIN BANDWIDTH AVGS: %s
                 MIN BANDWIDTH LASTS: %s
                 BANDWIDTH LASTS AVG: %s
                 NEW VIDEO URL: %s''' % infos)


def get_quality_ids(mediadata, Bandwidths):
    minband = min(Bandwidths[1:])[-1]
    logging.debug("MINBANDS: %s" % Bandwidths[1:])
    mid = len(mediadata) - 1
    aid = 1
    audioband = 144000
    logging.debug('Videodata Attribs: %s' % mediadata[mid][minvid].attrib)
    for idv in range(len(mediadata[mid])):
        manband = mediadata[mid][idv].attrib.get('bandwidth', 0)
        manband = int(manband) + audioband
        vid = idv
        if manband > minband:
            #  or manband / 8 > maxband * 1024
            break
    vid = max(idv - 1, minvid)
    logging.debug('VID SELECTED: %s' % vid)
    return (aid, vid)


def get_mediadata(videoid):
    # https://www.youtube.com/oembed?url=[Youtubewatchurl]&format=json
    url = 'https://www.youtube.com/get_video_info?video_id=' + videoid
    r = session.get(url)
    if not r.ok:
        logging.fatal('Http Error %s trying to get video info.' % r.status_code)
        return 1
    ytdict = parse_qs(r.text, strict_parsing=True)
    if ytdict:
        metadata = {}
        streamtype = ytdict.get('qoe_cat')
        if streamtype:
            otf = True
        else:
            otf = False
        metadata['Otf'] = otf
        logging.debug('stream type: ' + str(streamtype))
    else:
        logging.info('Could not get main dictionary...')
        return 1
    ytpresp = json.loads(ytdict.get('player_response', [0])[0])
    if ytpresp:
        playable = ytpresp.get('playabilityStatus')
        pstatus = playable.get('status')
        reason = playable.get('reason')
        if pstatus and pstatus == 'UNPLAYABLE':
            logging.info('Video status: UNPLAYABLE')
            if reason:
                href = re.findall(r'(?<=href=").*?(?=")', reason)
                if href:
                    reco = re.findall(r'(?<=>).*?(?=<)', reason)
                    if reco:
                        reco = reco[0] + ' --> ' + href[0]
                        realreason = re.findall(r'(?<=\n).*$', reason)
                        if realreason:
                            reason = realreason[0] + '\n' + reco
                logging.info("Reason: %s" % reason)
            return 1
    else:
        logging.info('Could not extract player response data...')
        return 1
    logging.info("Video id: %s" % videoid)
    # Player configs json:
    # ytpjs = re.findall(r'ytplayer.config = ({.*?});', r.text)
    # if not ytpjs:
    #    return 1
    # ytpjson = json.loads(ytpjs[0])
    # ytpargs = ytpjson['args']
    liveaheadsecs = ytdict.get('live_readahead_seconds')
    liveaheadchunk = ytdict.get('live_chunk_readahead')
    latencyclass = ytdict.get('latency_class')
    livestream = ytdict.get('livestream')
    liveplayback = ytdict.get('live_playback')
    # lengthsecs = ytpjson['args']['length_seconds']
    # ytpresp = json.loads(ytpjson['args']['player_response'])
    ytpconfig = ytpresp.get('playerConfig')
    if ytpconfig:
        audioconfig = ytpconfig.get('audioConfig')
        streamconfig = ytpconfig.get('streamSelectionConfig')
        if streamconfig:
            maxbitrate = streamconfig.get('maxBitrate')
            logging.info('MaxBitrate: ' + maxbitrate)
    # Get Video Details:
    videodetails = ytpresp.get('videoDetails')
    if videodetails:
        metadata.update(videodetails)
        title = videodetails.get('title')
        description = videodetails.get('shortDescription')
        author = videodetails.get('author')
        isprivate = videodetails.get('isPrivate')
        viewcount = videodetails.get('viewCount')
        lengthsecs = videodetails['lengthSeconds']
        postlivedvr = videodetails.get('isPostLiveDvr')
        livecontent = videodetails.get('isLiveContent')
        live = videodetails.get('isLive', False)
        lowlatency = videodetails.get('isLowLatencyLiveStream')
        livedvr = videodetails.get('isLiveDvrEnabled')
    # Get streaming Data:
    streamingdata = ytpresp.get('streamingData')
    if streamingdata:
        dashmanurl = streamingdata.get('dashManifestUrl')
        hlsmanurl = streamingdata.get('hlsManifestUrl')
        manifesturl = dashmanurl
        metadata['ManifestUrl'] = manifesturl
        formats = streamingdata.get('formats')
        adaptivefmts = streamingdata.get('adaptiveFormats')
        if adaptivefmts:
            # logging.debug('ADAPTIVEFMTS: ' + str(adaptivefmts))
            adaptivefmts.sort(key=lambda fmt: fmt.get('bitrate', 0))
            '''streamtype = adaptivefmts[-1].get('type')
            if streamtype == 'FORMAT_STREAM_TYPE_OTF':
                otf = True
            metadata['Otf'] = otf
            logging.debug('stream type: ' + str(streamtype))'''
    else:
        manifesturl = None
        logging.info('No data found to play media')
        return 1
    if not latencyclass:
        latencyclass = videodetails.get('latencyClass')
        if latencyclass:
            latencyclass = re.findall('(?<=LATENCY_).+', latencyclass)
            metadata['latencyClass'] = latencyclass[0]
    if not livecontent or not manifesturl:
        audiodata = []
        videodata = []
        for i in range(len(adaptivefmts)):
            mtype = adaptivefmts[i]['mimeType'].split('; ')
            if mtype[0] == 'audio/mp4' and mtype[1][8:11] == 'mp4':
                audiodata.append(adaptivefmts[i])
            elif mtype[0] == 'video/mp4' and mtype[1][8:11] == 'avc':
                videodata.append(adaptivefmts[i])
        logging.debug('Videodata: %s' % videodata)
    # logging Details:
    logging.info('View count: ' + viewcount)
    logging.debug('postLiveDVR: ' + str(postlivedvr))
    logging.debug('reason: ' + str(reason))
    logging.debug('liveplayback: ' + str(liveplayback))
    logging.debug('livestream: ' + str(livestream))
    logging.debug('title: ' + str(title))
    logging.debug('description: ' + str(description))
    logging.debug('isprivate: ' + str(isprivate))
    logging.debug('islive: ' + str(live))
    logging.debug('islivecontent: ' + str(livecontent))
    logging.debug('islowlatency: ' + str(lowlatency))
    logging.debug('islivedvr: ' + str(livedvr))
    logging.debug('latencyclass: ' + str(latencyclass))
    logging.debug('live readahead secs: ' + str(liveaheadsecs))
    logging.debug('live readahead chunks: ' + str(liveaheadchunk))
    if manifesturl:
        manifesturl += '/keepalive/yes'
        logging.debug("Manifest URL: %s" % manifesturl)
        rawmanifest = session.get(manifesturl, headers=None, stream=True)
        if not rawmanifest.ok:
            logging.info("Error getting manifest...")
            return 1
        if reason:
            print(reason)
            '''else:
                print('Stream no longer live...')
            '''
            if postlivedvr and not args.offset:
                print('Live Stream recently ended, retry with a timeoffset ' +
                      'to play from.')
                return 1
        tree = ET.fromstring(rawmanifest.text)
        startnumber = int(tree[0][0].attrib.get('startNumber', 0))
        earliestseqnum = int(tree.get('{http://youtube.com/yt/2012/10/10}' +
                                      'earliestMediaSequence', 0))
        timescale = float(tree[0][0].get('timescale', 0))
        buffersecs = tree.get('timeShiftBufferDepth')
        if buffersecs:
            buffersecs = float(buffersecs[2:-1])
        minuperiod = tree[0].get('minimumUpdatePeriod')
        if minuperiod:
            segsecs = int(minuperiod[2:-1])
        elif timescale:
            segsecs = round(float(tree[0][0][0][0].get('d')) / timescale)
        # Media Metadata:
        if otf:
            if not lowlatency:
                segsecs = 5
            ida = 0
            idv = 1
        else:
            ida = 1
            idv = 2
        audiodata = tree[0][ida].findall("[@mimeType='audio/mp4']/")
        videodata = tree[0][idv].findall("[@mimeType='video/mp4']/")
        # Sort by bandwidth needed:
        for mtype in audiodata, videodata:
            mtype.sort(key=lambda mid: int(mid.attrib.get('bandwidth', 0)))
        fps_string = 'FrameRate'
    else:
        logging.info('Dash Manifest URL not available...')
        if adaptivefmts:
            logging.info('Playing manifestless video...')
            logging.info('Adaptative video disabled...')
            fps_string = 'fps'
            segsecs = 5
            buffersecs, earliestseqnum, startnumber = 0, 0, 0
        else:
            logging.info('No dynamic video to play...')
            return 1
    logging.info("VIDEO IS LIVE: %s" % live)
    logging.info("Total video Qualitys Available: %s" % len(videodata))
    # Filter video types by max height, width, fps and badnwidth:
    idx = 0
    while idx < len(videodata):
        # logging.info(videodata[idx].get('bandwidth'))
        videofps = int(videodata[idx].get(fps_string, 0))
        videoheight = int(videodata[idx].get('height', 0))
        videowidth = int(videodata[idx].get('width', 0))
        if livecontent and manifesturl:
            videoband = int(videodata[idx].attrib.get('bandwidth', 0))
        else:
            videoband = 0
        if(videofps > args.maxfps or videoheight > args.maxheight
           or videowidth > args.maxwidth or
           videoband / 8 > args.maxband * 1024):
                del videodata[idx]
        else:
            idx += 1
    logging.info("Total video Qualitys Choosen: %s" % len(videodata))
    return (segsecs, audiodata, videodata, buffersecs, earliestseqnum,
            startnumber, metadata)


def ffmuxer(ffmpegbin, ffmuxerstdout, apipe, vpipe):
    ffmpegargs = '%s -y -v %s -nostdin ' % (ffmpegbin, ffloglevel)
    ffmpegargsinputs = '-thread_queue_size 2000000 -flags +low_delay '
    if apipe:
        ffmpegargs += ffmpegargsinputs + '-i async:pipe:%s ' % apipe
        fds = (apipe, vpipe)
    else:
        fds = (vpipe,)
    ffmpegargs += ffmpegargsinputs + ' -i async:pipe:%s ' % vpipe
    ffmpegargs += '-f mpegts -bsf:v h264_mp4toannexb -c copy -copyts '
    ffmpegargs += '-flags +low_delay -'
    ffmpegmuxer = subprocess.Popen(shlex.split(ffmpegargs),
                                   bufsize=10485760,
                                   stdout=ffmuxerstdout,
                                   stderr=None,
                                   close_fds=True,
                                   pass_fds=fds)
    fftries = 0
    while ffmpegmuxer.poll() is not None:
        print("WAITING FFMPEG TO OPEN...")
        if fftries < 5:
            time.sleep(1)
        else:
            raise Exception
        fftries += 1
    return ffmpegmuxer


def get_media(data):
    baseurl, segmenturl, pipe, init = data
    conerr = 0
    twbytes = 0
    acceptranges = None
    headnumber = 0
    timeouts = (3.05, max(4, segsecs * 3))
    headers = 0
    status = 0
    response = 0
    contentlength = 0
    end = 0
    walltimems = 0
    headtime = 0
    newurl = None
    rheaders = {}
    initbyte = 0
    playerclosed = 0
    # fd = os.fdopen(pipe, 'wb', 10485760)
    if not livecontent or not manifesturl:
        initbyte = 0
        maxbytes = 1048576
        rheaders['Range'] = 'bytes=%s-%s' % (initbyte, initbyte + maxbytes)
    else:
        maxbytes = 0
    while True:
        try:
            if twbytes:
                # fd.flush()
                logging.debug("Trying to resume from byte: %s" % twbytes)
                sbyte = initbyte + twbytes
                if maxbytes:
                    ebyte = sbyte + maxbytes
                    if ebyte > contentlength:
                        ebyte = contentlength
                else:
                    ebyte = ''

                rheaders['Range'] = 'bytes=%s-%s' % (sbyte, ebyte)
            url = baseurl + segmenturl
            gettime = time.time()
            if init == 1:
                request = session.head
            else:
                request = session.get

            with request(url, stream=True, timeout=timeouts,
                         allow_redirects=True, headers=rheaders) as response:
                basedelay = round((time.time() - gettime), 4)
                # Getting metadata from headers:
                headers = response.headers
                reqheaders = response.request.headers
                headnumber = int(headers.get('X-Head-Seqnum', 0))
                sequencenum = int(headers.get('X-Sequence-Num', 0))
                pheadtime = headtime
                headtime = int(headers.get('X-Head-Time-Sec', 0))
                pwalltimems = walltimems
                walltimems = int(headers.get('X-Walltime-Ms', 0))
                if live and pwalltimems and pheadtime:
                    walldiff = (walltimems - pwalltimems) / 1000
                    headdiff = (headtime - pheadtime) / 1
                    if(walldiff > segsecs * 1.5 and headdiff == 0):
                        logging.debug('Wallsdif > SegmSecs: %s' % walldiff)
                        logging.info('Transmission ended...')
                        end = 1
                if not contentlength:
                    contentrange = headers.get(
                                             'Content-Range', '').split('/')[-1]
                    if contentrange and contentrange != '*':
                        contentlength = int(contentrange)
                    else:
                        contentlength = int(headers.get('Content-Length', 0))
                acceptranges = headers.get('Accept-Ranges', 0)
                cachecontrol = headers.get('Cache-Control', 0)
                headtimems = int(headers.get('X-Head-Time-Millis', 0))
                segmentlmt = int(headers.get('X-Segment-Lmt', 0))
                contenttype = headers.get('Content-Type', 0)
                if contenttype != 'audio/mp4':
                    bandwidthavg = int(headers.get('X-Bandwidth-Avg', 0))
                    bandwidthest = int(headers.get('X-Bandwidth-Est', 0))
                    bandwidthest2 = int(headers.get('X-Bandwidth-Est2', 0))
                    bandwidthest3 = int(headers.get('X-Bandwidth-Est3', 0))
                else:
                    bandwidthavg = 0
                    bandwidthest = 0
                    bandwidthest2 = 0
                    bandwidthest3 = 0

                status = response.status_code
                connection = response.connection
                if live or postlivedvr:
                    # logging.debug('HEADERS: %s' % headers)
                    # logging.debug('REQ HEADERS: %s' % reqheaders)
                    # logging.debug("HEADTIMES : %s s %s ms" %
                    #               (headtime, headtimems))
                    logging.debug('HEADNUMBER: %s' % headnumber)
                    logging.debug('SEQUENCENUMBER: %s' % sequencenum)
                    # logging.debug("WALLTIMEMS  : %s" % (walltimems))
                    # logging.debug("SEGMENT LMT: %s" % (segmentlmt))
                    # logging.debug('ACCEPT-RANGES: %s' % acceptranges)
                    # logging.debug("CONTENT LENGTH: %s" % contentlength)
                # Check status codes:
                if status == 200 or status == 206:
                    logging.debug("Getting Media Content.....")
                    if response.history:
                        if response.history[-1].status_code == 302:
                            rurl = response.url + "/"
                            if segmenturl:
                                newurl = rurl.replace(segmenturl + "/", '')
                            elif not livecontent:
                                baseurl = rurl[0:-1]
                            logging.debug('SAVING NEW URL: %s' % newurl)
                    # Write media content to ffmpeg or player pipes:
                    if otf and not twbytes and init:
                        twbytes = os.write(pipe, init)
                    if init != 1:
                        logging.debug("WRITING TO PIPE: " + str(pipe))
                        for chunk in response.iter_content(chunk_size=1024):
                            if player.poll() is not None:
                                end = 1
                                break
                            twbytes += os.write(pipe, chunk)
                            # os.fsync(pipe)
                            # fd.flush()
                        if not end:
                            if twbytes < contentlength:
                                continue
                            elif not manifesturl:
                                end = 1
                        if(live or postlivedvr or not manifesturl or
                           (otf and contenttype == 'video/mp4')):
                                os.close(pipe)
                                # fd.flush()
                                # fd.close()
                    info = (status, basedelay, headnumber, headtimems,
                            sequencenum, walltimems, segmentlmt, contentlength,
                            cachecontrol, bandwidthavg, bandwidthest,
                            bandwidthest2, bandwidthest3, connection,
                            contenttype, newurl, twbytes, end)
                    logging.debug('Bytes written: %s' % twbytes)
                    return info
                else:
                    logging.debug('Status Code: %s' % status)
                    logging.debug('REQUEST HEADERS: %s' %
                                  response.request.headers)
                    logging.debug('HEADERS: %s' % response.headers)
                    logging.debug("REQUEST URL: " + url)
                    if status == 204:
                        logging.debug('Retrying in %s secs' % segsecs)
                    if status == 503:
                        logging.debug("Trying redirection...")
                        gvideohost = url.split('/')[2].split('.')[0]
                        url = url.replace(gvideohost, "redirector")
                    elif status == 404 or status == 400 or status == 403:
                        if live:
                            logging.debug('Refreshing metadata...')
                            metadata = get_mediadata(videoid)
                            if(type(metadata) is tuple and
                               not metadata[6].get('isLive')):
                                logging.debug("Transmission looks ended...")
                                end = 1
                    time.sleep(segsecs)
                    continue
        except (BrokenPipeError) as oserr:
            logging.debug("Exception Ocurred: %s %s" % (oserr, str(oserr.args)))
            break
        except (requests.exceptions.ConnectionError) as exception:
            logging.debug("Requests HTTP Exception Ocurred: %s" % exception)
            logging.debug("Total bytes written: %s" % twbytes)
            headtime = 0
            if headers:
                logging.debug("HEADERS: %s" % headers)
            if status:
                logging.debug("LAST STATUS CODE: %s" % status)
            connerr = 1
            time.sleep(segsecs)
            continue
        except (requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ReadTimeout) as exception:
            logging.debug("Requests Exception Ocurred: %s" % exception)
            logging.debug("Total bytes written: %s" % twbytes)
            headtime = 0
            if headers:
                logging.debug("HEADERS: %s" % headers)
            if status:
                logging.debug("LAST STATUS CODE: %s" % status)
            connerr = 1
            time.sleep(segsecs)
            continue


def closefds(totalpipes):
    fds = []
    if type(totalpipes) is list:
        for segmenttuples in totalpipes:
            if type(segmenttuples) is list:
                for pipetuple in segmenttuples:
                    if type(pipetuple) is tuple:
                        for fd in pipetuple:
                            if type(fd) is int:
                                fds.append(fd)
                    elif type(pipetuple) is int:
                        fds.append(fd)
            elif type(segmenttuples) is int:
                fds.append(segmenttuples)
    elif type(totalpipes) is int:
        fds.append(totalpipes)
    for fd in fds:
        try:
            if fd > 2:
                logging.debug('Closing fd: %s' % fd)
                os.close(fd)
        except OSError:
            pass


if __name__ == '__main__':
    global ffmpegmuxer, abaseurls, vbaseurls, args, livecontent, live, otf
    global segsecs, apiurllive, videoid, minvid, lowlatency, manifesturl
    assert ('linux' in sys.platform), "This code runs on Linux only."
    parser = argparse.ArgumentParser(prog='ytdash',
                                     description='Youtube DASH video playback.')
    parser.add_argument('urls', metavar='URL|QUERY', type=str, nargs='+',
                        help='URLs or search queries of videos to play')
    parser.add_argument('--version', action='version', version='%(prog)s 0.11')
    parser.add_argument('-quiet', '-q', action='store_true',
                        help='enable quiet mode (default: %(default)s)')
    parser.add_argument('-search', '-s', action='store_true',
                        help='search mode (default: %(default)s)')
    parser.add_argument('-nonlive', '-nl', action='store_true',
                        help='search also non-live videos ' +
                        '(default: %(default)s)')
    parser.add_argument('-sortby', '-sb', type=str, default='relevance',
                        choices=['relevance', 'viewCount', 'videoCount', 'date',
                                 'rating', 'title', 'rating'],
                        help='sorting order for the search results ' +
                        '(default: %(default)s)')
    parser.add_argument('-eventtype', '-et', type=str, default='live',
                        choices=['live', 'upcoming', 'completed'],
                        help='filter results by live event type' +
                        '(default: %(default)s)')
    parser.add_argument('-safesearch', '-ss', type=str, default='moderate',
                        choices=['moderate', 'none', 'strict'],
                        help='Safe search mode to use if any' +
                        '(default: %(default)s)')
    parser.add_argument('-duration', '-dur', type=str, default='any',
                        choices=['any', 'long', 'medium', 'short'],
                        help='filter results by video duration' +
                        '(default: %(default)s)')
    parser.add_argument('-videotype', '-vt', type=str, default='any',
                        choices=['any', 'episode', 'movie'],
                        help='filter results by video type ' +
                        '(default: %(default)s)')
    parser.add_argument('-type', type=str, default='video',
                        choices=['video', 'channel', 'playlist'],
                        help='filter results by type of resource ' +
                        '(default: %(default)s)')
    parser.add_argument('-definition', '-vd', type=str, default='any',
                        choices=['hd', 'sd', 'any'],
                        help='filter results by video definition ' +
                        '(default: %(default)s)')
    parser.add_argument('-license', type=str, default='any',
                        choices=['creativeCommon', 'youtube', 'any'],
                        help='filter results by video livense type ' +
                        '(default: %(default)s)')
    parser.add_argument('-maxresults', '-mr', type=int, default=5,
                        help='search max results (default: %(default)s)')
    parser.add_argument('-debug', '-d', action='store_true',
                        help='enable debug mode  (default: %(default)s)')
    parser.add_argument('-player', '-p', type=str, default='mpv',
                        help='player bin name, (default: %(default)s)')
    parser.add_argument('-maxfps', '-mf', type=int, default=60,
                        help='max video fps to allow (default: %(default)s)')
    parser.add_argument('-maxband', '-mb', type=int, default=700,
                        help='max video bandwidth in kB/s to allow when ' +
                        ' possible (default: %(default)s)')
    parser.add_argument('-maxheight', '-mh', type=int, default=720,
                        help='max video heigth to allow (default: %(default)s)')
    parser.add_argument('-maxwidth', '-mw', type=int, default=1360,
                        help='max video width to allow (default: %(default)s)')
    parser.add_argument('-ffmpeg', '-ff', type=str, default='ffmpeg',
                        help='ffmpeg location route (default: %(default)s)')
    parser.add_argument('-fixed', '-f', action='store_true',
                        help='Play a fixed video quality instead of doing' +
                        ' bandwidth adaptive quality change, This is the max' +
                        ' set from options (default: %(default)s)')
    parser.add_argument('-offset', '-o', type=str, default='',
                        help='Time or segments offset from where start ' +
                        'to play, (i.e: 2h, 210m, 3000s or 152456, ' +
                        "for hours, minutes, seconds and " +
                        "nº of segment respectively.)")
    args = parser.parse_args()
    # Logging:
    if args.debug:
        loglevel = logging.DEBUG
        ffloglevel = 'warning'
    elif args.quiet:
        loglevel = logging.WARN
        ffloglevel = 'fatal'
    else:
        loglevel = logging.INFO
        ffloglevel = 'fatal'
    logging.basicConfig(
        level=loglevel, filename="logfile", filemode="w+",
        format="%(asctime)-15s %(levelname)-8s %(message)s")
    console = logging.StreamHandler()
    console.setLevel(loglevel)
    # add the handler to the root logger
    logging.getLogger('').addHandler(console)

    if os.path.isfile('/tmp/dash2.0.pid'):
        with open('/tmp/dash2.0.pid', 'r') as fd:
            prevpid = fd.read()
            if prevpid:
                try:
                    os.killpg(int(prevpid), signal.SIGTERM)
                    logging.debug("Killed previous instance...")
                except ProcessLookupError:
                    logging.debug("Process does not exist...")
    os.setpgrp()
    with open('/tmp/dash2.0.pid', 'w') as fd:
        fd.write(str(os.getpgrp()))

    if args.player == 'mpv':
        # max RAM cached media size downloaded after pause in Mb:
        cachesize = 7
        backcachesize = 5  # max back RAM cached media played/skipped to keep,Mb
        totalcachesize = backcachesize + cachesize
        playerbaseargs = (' --input-terminal=no ')
        #              ' --rebase-start-time=yes'
        #              '--profile=low-latency'
        if not args.debug:
            playerbaseargs += ' --really-quiet=yes '
    elif args.player == 'vlc':
        playerbaseargs = ' --file-caching=5000 '
    else:
        playerbaseargs = ' - '
    logging.debug('PLAYER CMD: ' + args.player + playerbaseargs)

    autoresync = 1  # Drop segments on high delays to keep live
    with requests.Session() as session:
        vsegoffset = 3
        init = None
        ffmpegbase = None
        player = None
        videodata = None
        vid = 0
        aid = 0
        minsegms = 1
        ffmpegmuxer = None
        BandwidthsAvgs = [0, 1, 2, 3]
        session.verify = True
        session.mount('https://', requests.adapters.HTTPAdapter(
                        pool_connections=10,
                        pool_maxsize=10,
                        max_retries=1))
        # (X11; Linux x86_64)
        session.headers['User-Agent'] += ' ytdash/0.11 (gzip)'
        for urlid in range(len(args.urls)):
            playerargs = playerbaseargs
            url = urlparse(args.urls[urlid])
            urlquery = url.query
            urlhost = url.hostname
            urlfolders = url.path.split('/')
            idre = re.compile('^[A-z0-9_-]{11}$')
            videoid = None
            channelid = None
            userid = None
            if urlhost:
                if url.hostname[-8:] == "youtu.be":
                    videoid = urlfolders[1]
                elif url.hostname[-11:] == "youtube.com":
                    if url.path == '/watch':
                        videoid = parse_qs(url.query).get('v', [0])[0]
                    elif url.path == '/embed':
                        videoid = urlfolders[2]
                    elif url.path[0:8] == '/channel':
                        channelid = urlfolders[2]
                    elif url.path[0:5] == '/user':
                        userid = urlfolders[2]
                    if channelid or userid:
                        if not args.search:
                            logging.info('Channel URL given but search ' +
                                         'disabled, enable search mode to' +
                                         ' play the videos found')
                            quit()
            elif not args.search:
                if url.path and re.match(idre, url.path):
                    videoid = url.path
                else:
                    logging.info('Could not find a video or channel id' +
                                 ' in the given string')
                    quit()
            if videoid:
                apitype = 'videos'
            else:
                apibaseurl = 'https://www.googleapis.com/youtube/v3/'
                apiparams = {}
                apiparams['part'] = 'snippet'
                apiparams['key'] = 'AIzaSyAWOONC01ILGs4dh8vnCJDO4trYbFTH4zQ'
                if userid:
                    apitype = 'channels'
                    apiurl = apibaseurl + apitype
                    apiparams['forUsername'] = userid
                    r = requests.get(apiurl, params=apiparams)
                    channelitems = r.json().get('items')
                    if channelitems:
                        channelid = channelitems[0].get('id')
                    else:
                        logging.info('Could not get user channel id')
                        quit()
                    del apiparams['forUsername']
                apitype = 'search'
                apiparams['type'] = 'video'
                apiparams['order'] = args.sortby
                if not args.nonlive:
                    apiparams['eventType'] = args.eventtype
                apiparams['videoDimension'] = '2d'
                apiparams['regionCode'] = 'AR'
                apiparams['safeSearch'] = args.safesearch
                apiparams['videoDuration'] = args.duration
                apiparams['videoType'] = args.videotype
                apiparams['type'] = args.type
                apiparams['videoLicense'] = args.license
                apiparams['videoDefinition'] = args.definition  # high|any
                apiparams['maxResults'] = args.maxresults
                apiparams['videoEmbeddable'] = 'true'
                apiparams['videoSyndicated'] = 'true'
                if channelid:
                    apiparams['channelId'] = channelid
                else:
                    apiparams['q'] = args.urls[urlid]
                apiparams['fields'] = ('items(id,snippet/title,snippet/' +
                                       'channelTitle,snippet/description,' +
                                       'snippet/liveBroadcastContent)')
                apiurl = apibaseurl + apitype
                try:
                    r = requests.get(apiurl, params=apiparams)
                    logging.debug("API URL: " + r.url)
                    if not r.ok:
                        status = r.status_code
                        if status == 400:
                            reason = r.json()['error']['message']
                            logging.info('Bad API request: ' + reason)
                        else:
                            logging.info('Error code %s API request ' + status)
                        quit()
                except requests.exceptions.ConnectionError:
                    logging.warn("Connection Error, check net connections...")
                    quit()
                items = r.json().get('items')
                if items:
                    print("Videos found:")
                else:
                    print("No videos found.")
                    quit()
                # while True:
                answer = None
                itemnum = 1
                for item in items:
                    snippet = item['snippet']
                    title = snippet['title']
                    channeltitle = snippet["channelTitle"]
                    description = snippet['description'][:58:] + '...'
                    livebroad = snippet['liveBroadcastContent']
                    if livebroad == 'none':
                        livebroad = False
                    else:
                        livebroad = True
                    print('%s) %s\n' % (itemnum, title) +
                          '    * Description: %s\n' % description +
                          '    * Channel: %s\n' % channeltitle +
                          '    * Live: %s' % livebroad)
                    itemnum += 1
                if args.search and len(items) > 1:
                    print('Enter nº of video to play or "q" to exit.')
                    #      'Enter to play from the first one.')
                    while True:
                        answer = input()
                        if(re.match(r'^[0-9]+$', answer) and
                           0 < int(answer) <= len(items)):
                                answer = int(answer)
                        if type(answer) is int:
                            break
                        elif answer == 'q' or answer == 'Q':
                            quit()
                        else:
                            print('Invalid input, only integers from 1 to' +
                                  ' %s are accepted...' % len(items))
                    if answer:
                        item = items[answer - 1]
                else:
                    item = items[0]
                title += ' - ' + channeltitle
                if not videoid:
                    videoid = item['id']['videoId']
            # Get the manifest and all its Infos
            mediadata = get_mediadata(videoid)
            # print(metadata)
            if mediadata == 1:
                continue
            elif mediadata == 2:
                break
            else:
                segsecs = mediadata[0]
                audiodata = mediadata[1]
                videodata = mediadata[2]
                buffersecs = mediadata[3]
                earliestseqnum = mediadata[4]
                startnumber = mediadata[5]
                metadata = mediadata[6]
                title = metadata.get('title')
                description = metadata.get('shortDescription')
                author = metadata.get('author')
                private = metadata['isPrivate']
                lengthsecs = metadata['lengthSeconds']
                postlivedvr = metadata.get('isPostLiveDvr')
                livecontent = metadata.get('isLiveContent')  # media is/was live
                live = metadata.get('isLive')
                lowlatency = metadata.get('isLowLatencyLiveStream')
                livedvr = metadata.get('isLiveDvrEnabled')
                otf = metadata.get('Otf')
                manifesturl = metadata.get('ManifestUrl')
            logging.debug("Start number: " + str(startnumber))
            # Check the Url and Get info from Headers:
            maxaid = len(audiodata) - 1
            maxvid = len(videodata) - 1
            if live:
                maxsegms = 3
                if segsecs == 1:
                    logging.info('--Live mode: ULTRA LOW LATENCY--')
                    # maxsegms = 3
                    minsegms = 2
                elif segsecs == 2:
                    logging.info('--Live mode: LOW LATENCY--')
                elif segsecs == 5:
                    logging.info('--Live mode: NORMAL LATENCY--')
                    # maxsegms = 3
            else:
                maxsegms = 3
            logging.debug("Segment duration in secs: " + str(segsecs))
            if live or postlivedvr:
                if args.fixed:
                    aid = maxaid
                    vid = maxvid
                else:
                    aid = 1
                    vid = 1
                inita = 1
                initv = 1
                aidu = 1
                minvid = 1
                Bandwidths = [[0], [0], [0], [0]]
                logging.debug("Back buffer depth in secs: " + str(buffersecs))
                logging.debug("Earliest seq number: " + str(earliestseqnum))
                # max Nº of pending segments allowed before forcing resync:
                segmresynclimit = buffersecs/segsecs
                headnumber = len(audiodata[1][2]) + earliestseqnum - 1
                if startnumber > earliestseqnum:
                    segmresynclimit = startnumber - earliestseqnum
                    if vsegoffset > segmresynclimit:
                        vsegoffset = segmresynclimit - 1
                elif args.offset:
                    offsetnum = args.offset[0:-1]
                    offsetunit = args.offset[-1]
                    if re.match('^[0-9]+$', offsetnum):
                        floffset = float(args.offset[0:-1])
                    else:
                        print('Invalid time offset format...')
                        quit()
                    if offsetunit == "h":
                        vsegoffset = int((floffset*3600)/segsecs)
                        if floffset > 4:
                            logging.debug('''The max back buffer hours is %s,
                                            playing
                                            from oldest segment available'''
                                          % str(buffersecs/3600))
                    elif offsetunit == "m":
                        vsegoffset = int((floffset*60)/segsecs)
                        if floffset > 240:
                            logging.debug('''The max back buffer minutes is %s,
                                         playing from oldest segment available
                                         ''' % str(buffersecs/60))
                    elif offsetunit == "s":
                        vsegoffset = int(int(floffset)/segsecs)
                        if floffset > buffersecs:
                            logging.debug('The max backbuffer seconds ' +
                                          'is %s, playing ' % buffersecs +
                                          'from there')
                    elif re.match('^[0-9]+$', args.offset):
                        if headnumber - int(args.offset) >= earliestseqnum:
                            vsegoffset = int(args.offset)
                        else:
                            logging.debug("The oldest segment to "  +
                                          "play is %s, playing " % buffersecs +
                                          "from there")
                    else:
                        logging.debug("No valid value entered for third " +
                                      "argument, acepted values are; " +
                                      " i.e: 2h, 210m or 3000s or 152456, " +
                                      "for hours, minutes, seconds and " +
                                      "nº of segment respectively.")
                    vsegoffset = min(segmresynclimit, vsegoffset, headnumber)
                vsegoffset = asegoffset = int(vsegoffset)
                seqnumber = int(headnumber - vsegoffset)
                if lowlatency:
                    seqnumber = ''
                logging.debug('HEADNUMBER: %s, ' % headnumber +
                              'START NUMBER: %s, ' % startnumber +
                              'SEQNUMBER: %s, ' % seqnumber)

                logging.debug("AUDIOMAINURL %s" % audiodata[aid][1].text)
                logging.debug("VIDEOMAINURL %s" % videodata[vid][0].text)
            else:
                apipe = 0
                vid = int(len(videodata) / 1) - 1
                aidu = 1
                minvid = 2
                headnumber = 999
                seqnumber = 0
                remainsegms = 0
                segmresynclimit = 99999
                selectedbandwidth = [0, 0]
                nextbandwidth = [0, 0]
                minbandavg = [0, 0]
                minbandlast = [0, 0]
                bandslastavg = [0, 0]
                bandwidthdown = 1
                bandwidthup = 1
                if otf:
                    aid = 2
                    vsegoffset = len(videodata[2][1]) - 1
                    asegoffset = len(audiodata[2][2]) - 1
                    initaurl = audiodata[aid][1].text
                    initaurl += audiodata[aid][2][0].get('sourceURL')
                    initvurl = videodata[vid][0].text
                    initvurl += videodata[vid][1][0].get('sourceURL')
                else:
                    aid = 0
                    initaurl = audiodata[aid]['url']
                    rangestart = audiodata[aid]['initRange'].get('start')
                    rangeend = audiodata[aid]['indexRange'].get('end')
                    initaurl += '&range=%s-%s' % (rangestart, rangeend)
                    initvurl = videodata[vid]['url']
                    rangestart = videodata[vid]['initRange'].get('start')
                    rangeend = videodata[vid]['indexRange'].get('end')
                    if rangestart:
                        initvurl += '&range=%s-%s' % (rangestart, rangeend)
                logging.debug('ASEGOFFSET: %s' % asegoffset)
                initv = session.get(initvurl).content
                inita = session.get(initaurl).content
                logging.debug("IDS MEDIADATA %s %s" % (aid, vid))
                logging.debug("AUDIOMAINURL %s" % initaurl)
                logging.debug("VIDEOMAINURL %s" % initvurl)
                logging.debug('VSEGOFFSET: %s' % vsegoffset)

            # While End ---
            if manifesturl:
                analyzedur = int(segsecs * 1000000 * 2)
                ffbaseargs = args.ffmpeg + ' -v %s ' % ffloglevel
                ffbaseinputs = ' -thread_queue_size 150000 -flags +low_delay '
                ffbaseargs += ' -analyzeduration ' + str(analyzedur)
                if otf:
                    apipe = os.pipe()
                    # fda = os.fdopen(apipe[1], 'wb', 10485760)
                    ffbaseargs += ffbaseinputs + ' -i async:pipe:%s ' % apipe[0]
                    fffds = (apipe[0],)
                else:
                    fffds = ()
                ffbaseargs += ffbaseinputs + ' -i pipe:0 '
                ffbaseargs += ' -c copy -f nut '
                ffbaseargs += ' -bsf:v h264_mp4toannexb '
                ffbaseargs += ' -flags +low_delay pipe:1'
                ffmpegbase = subprocess.Popen(shlex.split(ffbaseargs),
                                              stdin=subprocess.PIPE,
                                              stdout=subprocess.PIPE,
                                              bufsize=10485760,
                                              pass_fds=fffds)
                playerstdin = ffmpegbase.stdout
                ffmuxerstdout = ffmpegbase.stdin
                playerargs += ' - '
                playerfds = ()
                if ffmpegbase.poll() is not None:
                    logging.info('Error openning main ffmpeg, quitting...')
                    quit()
            else:
                apipe = os.pipe()
                vpipe = os.pipe()
                if args.player == 'mpv':
                    playerargs += '--audio-file=%s ' % audiodata[aid]['url']
                elif args.player == 'vlc':
                    playerargs += '--input-slave="%s" ' % audiodata[aid]['url']
                playerargs += ' "%s" ' % videodata[vid]['url']
                playerstdin = None
                playerfds = ()
                ffmpegbase = None
                ffmpegmuxer = None
                ffmuxerstdout = None
            # fd2 = os.pipe()
            # fd3 = os.pipe()
            # fd4 = os.pipe()
            title = title.replace('"', "\'")
            description = description.replace('"', "\'")
            if args.player == 'mpv':
                playerargs += (' --title="%s" ' % (title + " - " + author) +
                               '--osd-playing-msg="%s" ' % description +
                               '--osd-font-size=%s ' % 25 +
                               '--osd-duration=%s ' % 20000 +
                               '--osd-align-x=center ' +
                               '--demuxer-max-bytes=%s ' %
                               (cachesize * 1048576) +
                               '--demuxer-seekable-cache=yes ' +
                               '--keep-open ')
                if manifesturl:
                    playerargs += ('--demuxer-lavf-analyzeduration=%s ' %
                                   int(segsecs * 3) +
                                   '--cache-backbuffer=%s ' %
                                   (backcachesize * 1024) +
                                   '--force-seekable=no ' +
                                   '--demuxer-max-back-bytes=%s ' %
                                   (backcachesize * 1048576) +
                                   '--cache=%s ' % (cachesize * 256))
                else:
                    playerargs += ('--cache-initial=%s ' % 512 +
                                   '--cache-pause-initial=yes ')
            elif args.player == 'vlc':
                playerargs += (' --input-title-format "%s" ' % (title + " - " +
                                                                author) +
                               '--no-video-title-show '
                               )
            playercmd = args.player + playerargs
            logging.debug('PLAYER COMMANDS' + playercmd)
            player = subprocess.Popen(shlex.split(playercmd),
                                      # env=env,
                                      bufsize=0,
                                      shell=False,
                                      stdin=playerstdin,
                                      stdout=None,
                                      stderr=None,
                                      pass_fds=playerfds)
            playertries = 0
            while player.poll() is not None:
                logging.debug("WAITING PLAYER TO OPEN...")
                if playertries < 5:
                    time.sleep(1)
                else:
                    logging.info('Could not open the player, check args...')
                    quit()
                playertries += 1
            if not manifesturl:
                player.wait()
                continue
            if ffmuxerstdout == "player":
                ffmuxerstdout = player.stdin
            elif ffmpegbase and ffmpegbase.poll() is None:
                ffmpegbase.stdout.close()
            # MAIN LOOP: ------------------------------------------------------#
            delays = [0]
            truedelays = []
            mindelay = 3600
            totaldelay = 0.0
            lastbands = []
            headnumbers = []
            basedelays = []
            headtimes = []
            walltimemss = []
            firstrun = 1
            avgsecs = 20
            arrayheaderslim = int(avgsecs / segsecs) * 2
            basedelayavg = 0
            end = 0
            # abytes = 1025400
            # vbytes = 0
            bandwidthup = 0
            bandwidthdown = 0
            ffmuxerdelay = 0
            bandwidthavg = 0
            cachecontrol = 0
            if live or postlivedvr:
                remainsegms = 1
            waiting = 0
            arraydelayslim = 3
            ssegms = 1
            pool = ThreadPoolExecutor(max_workers=2 * maxsegms)
            while True:
                starttime = time.time()
                try:
                    sequencenums = []
                    logging.debug('SEQNUMBER: %s, ' % seqnumber +
                                  'REMAIN SEGMS: %s' % remainsegms)
                    # Media downloads imapping:
                    segmsresults = []
                    rpipes = []
                    numbsegms = min(max(remainsegms, minsegms), maxsegms)
                    if not waiting:
                        for sid in range(numbsegms):
                            if not manifesturl:
                                segsecs = 5
                                amainurl = audiodata[aid]['url']
                                vmainurl = videodata[vid]['url']
                                vsegurl = asegurl = ''
                                rpipes = (apipe, vpipe)
                                initv = 0
                                inita = 0
                            else:
                                if not otf:
                                    apipe = os.pipe()
                                    rpipes.append([apipe[0]])
                                else:
                                    rpipes.append([0])
                                vpipe = os.pipe()
                                rpipes[sid].append(vpipe[0])
                                amainurl = audiodata[aid][aidu].text
                                vmainurl = videodata[vid][0].text
                                if postlivedvr or otf:
                                    if asegoffset:
                                        asegurl = audiodata[aid][2][-asegoffset]
                                        asegurl = asegurl.get('media')
                                    if vsegoffset:
                                        vsegurl = videodata[vid][1][-vsegoffset]
                                        vsegurl = vsegurl.get('media')
                                    else:
                                        raise Ended
                                    if otf or not initv == 1 == inita:
                                        vsegoffset -= 1
                                        asegoffset -= 1
                                elif live:
                                    if initv == 1 == inita:
                                        asegurl = vsegurl = ''
                                    else:
                                        asegurl = vsegurl = "sq/%s" % seqnumber
                                        seqnumber += 1
                            logging.debug('ASEGMENTURL: %s' % str(asegurl))
                            logging.debug('VSEGMENTURL: %s' % str(vsegurl))
                            # gargs = [[amainurl, asegurl, fda, inita],
                            #         [vmainurl, vsegurl, fdv, initv]]
                            ares = pool.submit(get_media, [amainurl, asegurl,
                                               apipe[1], inita])
                            vres = pool.submit(get_media, [vmainurl, vsegurl,
                                               vpipe[1], initv])
                            # athread = Thread(target=, args=('rout',)).start()
                            # vthread = Thread(target=get_media,
                            #                  args=('rout',)).start()
                            segmsresults.append((ares, vres))
                    logging.debug('Pipes: ' + str(rpipes))
                    # Media Downloads results:
                    pid = 0
                    for segmresult in segmsresults:
                        ffmuxerstarttimer = time.time()
                        if ffmpegmuxer is not None:
                            logging.debug('Waiting ffmpeg muxer...')
                            ffmpegmuxer.wait()
                            ''''waiting = 1
                            while waiting:
                                try:
                                    ffmpegmuxer.communicate(timeout=5)
                                    waiting = 0
                                except subprocess.TimeoutExpired:
                                    logging.info('Timed out...')
                                    if player.poll() is not None:
                                        logging.info("Player Closed... ")
                                        raise Ended
                                    continue

                        if not waiting:
                            ffmuxerdelay = round(
                                             time.time() - ffmuxerstarttimer, 4)
                        '''
                        if manifesturl and not inita == initv == 1:
                            logging.debug('FFmpeg read pipes: %s, %s' %
                                         (rpipes[pid][0], rpipes[pid][1]))
                            ffmpegmuxer = ffmuxer(args.ffmpeg, ffmuxerstdout,
                                                  rpipes[pid][0],
                                                  rpipes[pid][1])
                        for media in segmresult:
                            if type(media.result()) is tuple:
                                (status, basedelay, headnumber,
                                 headtimems, sequencenum, walltimems,
                                 segmentlmt, contentlength, cachecontrol,
                                 bandwidthavg, bandwidthest, bandwidthest2,
                                 bandwidthest3, connection, contenttype,
                                 newurl, wbytes, end) = media.result()
                                if headnumber:
                                    headnumbers.append(int(headnumber))
                                if headtimems:
                                    headtimes.append(int(headtimems))
                                if walltimems:
                                    walltimemss.append(int(walltimems))
                                if status == 200 or status == 206:
                                    if contenttype == "video/mp4":
                                        # vbytes += wbytes
                                        if newurl is not None:
                                            if not manifesturl:
                                                videodata[vid]['url'] = newurl
                                            else:
                                                videodata[vid][0].text = newurl
                                        vconn = connection
                                    elif contenttype == "audio/mp4":
                                        # abytes += wbytes
                                        if newurl is not None:
                                            if not manifesturl:
                                                audiodata[aid]['url'] = newurl
                                            else:
                                                audiodata[aid][1].text = newurl
                                        aconn = connection
                                    if basedelay:
                                        basedelays.append(basedelay)
                                    # if sequencenum:
                                    #    sequencenums.append(sequencenum)
                        if (otf or not inita == initv == 1) and manifesturl:
                            closefds(rpipes[pid])
                            pid += 1
                    if end:
                        raise Ended
                    # Limit Arrays
                    headtimes = headtimes[-arrayheaderslim:]
                    walltimemss = walltimemss[-arrayheaderslim:]
                    headnumbers = headnumbers[-arrayheaderslim:]
                    if headnumbers:
                        headnumber = max(headnumbers)
                        if not seqnumber:
                            seqnumber = headnumber
                        remainsegms = max(headnumber - seqnumber, 0)
                    # Check links expiring time(secs remaining):
                    if cachecontrol:
                        expiresecs = re.search(
                            'private, max-age=(.*)', cachecontrol)
                        if expiresecs:
                            expiresecs = int(expiresecs.group(1))
                            logging.debug('URLS EXPIRING IN %s S' % expiresecs)
                        if expiresecs is not None and expiresecs <= 20:
                            logging.debug('URL Expired %s, refreshing metadata.'
                                          % expiresecs)
                            metadata = get_mediadata(videoid)
                            if metadata == 1 or metadata == 2:
                                break
                            else:
                                segsecs = metadata[0]
                                audiodata = metadata[1]
                                videodata = metadata[2]
                                buffersecs = metadata[3]
                                earliestseqnum = metadata[4]
                                startnumber = metadata[5]
                    waiting = 0
                # EXCEPTIONS: -------------------------------------------------#
                except (Ended):
                    if player.poll() is not None:
                        logging.info("Player Closed... ")
                    else:
                        if live:
                            aconn.close()
                            vconn.close()
                        logging.info('Streaming completed, waiting player...')
                        player.wait()
                    for segmresult in segmsresults:
                        for media in segmresult:
                            media.cancel()
                    pool.shutdown(wait=True)
                    if ffmpegbase:
                        ffmpegbase.kill()
                        # ffmpegbase.communicate()
                        ffmpegbase.wait()
                    if ffmpegmuxer:
                        ffmpegmuxer.kill()
                        # ffmpegmuxer.communicate()
                        ffmpegmuxer.wait()
                    break
                # finally:
                #    closefds(rpipes)

                # Resyncing:
                if remainsegms > segmresynclimit:
                        seqnumber = headnumber - vsegoffset
                        logging.info('Resyncing...')
                # DELAYS: -----------------------------------------------------#
                # Min latency check:
                if not firstrun and mindelay > segsecs * 0.75:
                    logging.info('Min delay to high: %s seconds, ' % mindelay +
                                 'playback not realistic')
                basedelays = basedelays[-min(vsegoffset*2, 3*2):]
                if len(basedelays) > 0:
                    basedelayavg = round(sum(basedelays) / (
                                         2 * len(basedelays)), 4)
                    mindelay = min(min(basedelays) / 2, mindelay)
                    truedelay = round(delays[-1] - (max(basedelays[-2:])/2), 3)
                    truedelays.append(truedelay)
                    truedelays = truedelays[-arraydelayslim:]
                    truedelayavg = round(sum(truedelays) / len(truedelays), 3)
                if live:
                    ssegms = len(segmsresults)
                delay = round((time.time() - starttime - ffmuxerdelay) / ssegms,
                              4)
                delays.append(round(delay, 4))
                delays = delays[-arraydelayslim:]
                delayavg = round(sum(delays) / len(delays), 2)
                delaytogoup = max(round(segsecs / 3, 3), 1)
                threadsc = active_threads()
                logging.debug("--> DELAY TO UP: %s seconds\n" % delaytogoup +
                              "--> BASEDELAYS: %s seconds\n" % basedelays +
                              "--> BASEDELAY AVG: %s seconds\n" % basedelayavg +
                              "--> MIN DELAY: %s seconds\n" % mindelay +
                              "--> DELAYS: %s" % delays +
                              "--> DELAY AVG: %s seconds\n" % delayavg +
                              "--> FFMPEG DELAYS: %s\n" % ffmuxerdelay +
                              "--> Threads Count: %s\n" % threadsc)
                # -------------------------------------------------------------#

                # BANDWIDTHS: -------------------------------------------------#
                if not args.fixed and (live or postlivedvr):
                    if bandwidthavg:
                        Bandwidths[0].append(round(bandwidthavg * 8, 1))
                    if bandwidthest:
                        Bandwidths[1].append(round(bandwidthest * 8, 1))
                    if bandwidthest2:
                        Bandwidths[2].append(round(bandwidthest2 * 8, 1))
                    if bandwidthest3:
                        Bandwidths[3].append(round(bandwidthest3 * 8, 1))
                    # Limit subarrays to min segments offset length:
                    for i in range(len(Bandwidths)):
                        Bandwidths[i] = Bandwidths[i][-arrayheaderslim:]
                        BandwidthsAvgs[i] = int(sum(Bandwidths[i]) /
                                                len(Bandwidths[i]))
                        lastbands.append(Bandwidths[i][-1])
                    lastbands = lastbands[-4:]
                    #
                    pvid = max(vid - 1, minvid)
                    prevbandwidthb = int(
                                        videodata[pvid].attrib.get('bandwidth'))
                    selectedbandwidthb = int(
                                         videodata[vid].attrib.get('bandwidth'))
                    selectedbandwidth = [selectedbandwidthb + 144000,
                                         ((selectedbandwidthb + 144000)/8)/1024]
                    selectedbandwidth[1] = round(selectedbandwidth[1], 1)
                    nvid = min(vid + 1, len(videodata) - 1)
                    nextbandwidthb = int(
                                        videodata[nvid].attrib.get('bandwidth'))
                    nextbandwidth = [nextbandwidthb + 144000,
                                     ((nextbandwidthb + 144000)/8) / 1024]
                    nextbandwidth[1] = round(nextbandwidth[1], 1)
                    # Min values:
                    if BandwidthsAvgs[0] and int(segsecs) <= 5:
                        startid = 1
                        endid = None
                    else:
                        startid = 1
                        endid = None
                    minband = min(BandwidthsAvgs[startid:endid])
                    minbandavg = (minband, round((minband/8)/1024))
                    minbandlast = min(lastbands[startid:endid])
                    minbandlast = (minbandlast, round((minbandlast/8)/1024))
                    bandslastavg = round(sum(lastbands[startid:endid]) /
                                         len(lastbands[startid:endid]))
                    bandslastavg = (bandslastavg, round((bandslastavg/8)/1024))
                    print('\t' * 10, end='\r', flush=True)
                    print('Bandwidth Last Avg/Min: %skB/s' % bandslastavg[1] +
                          ' / %skB/s ' % minbandlast[1] +
                          ' - Delay Avg/Last %ss / %ss' %
                          (delayavg, delays[-1]), end='\r', flush=True)
                    bandwidthdown = 0
                    bandwidthup = 0
                    if(minbandlast[0] <= prevbandwidthb and
                       minbandlast[0] <= prevbandwidthb):
                            bandwidthdown = 1
                    else:
                        sensup = 1
                        if(minbandavg[0] > nextbandwidth[0] * sensup and
                           minbandlast[0] > nextbandwidth[0] * sensup):
                                bandwidthup = 1
                        logging.debug("Bandwidth UP: %s" % bandwidthup)
                    logging.debug("Bandwidth DOWN: %s" % bandwidthdown)
                    if inita and initv:
                        inita = 0
                        initv = 0
                        aid, vid = get_quality_ids((audiodata, videodata),
                                                   Bandwidths)
                else:
                    bandwidthup = 1
                    bandwidthdown = 1
                # CHECK TO GO DOWN: -------------------------------------------#
                if(not args.fixed and vid > minvid and ffmuxerdelay < 1 and
                   bandwidthdown and delays[-1] <= segsecs * len(videodata) and
                   ((segsecs <= 2 and delayavg > segsecs * 1.0 and
                     delays[-1] > segsecs + 0.0) or
                        (segsecs > 2 and delayavg > segsecs and
                         delays[-1] > segsecs))):
                            bandwidthdown = 0
                            sys.stdout.write('\rDelays detected, switching to' +
                                             ' lower video quality...')
                            sys.stdout.flush()
                            inertia = int(max(round(delayavg / segsecs, 4), 1))
                            vid = int(max(minvid, vid - inertia))
                            if otf:
                                initvurl = videodata[vid][0].text
                                initvurl += videodata[vid][1][0].get(
                                                                    'sourceURL')
                                initv = session.get(initvurl).content
                                logging.debug('Initurl' + initvurl)
                            log_(("DOWN", vid, remainsegms, mindelay,
                                 ffmuxerdelay, delaytogoup, truedelays,
                                 truedelayavg, basedelays, basedelayavg, delays,
                                 delayavg, selectedbandwidth[1],
                                 nextbandwidth[1], minbandavg[1],
                                 minbandlast[1], bandslastavg[1],
                                 videodata[vid][0].text))
                if remainsegms <= 0 or remainsegms > 10:
                    elapsed3 = round(time.time() - starttime, 4)
                    logging.debug("---> TOTAL LOCAL DELAY: " + str(elapsed3))
                    # CHECK TO GO UP: -----------------------------------------#
                    # General check:
                    if(not args.fixed and vid < maxvid and bandwidthup and
                       basedelayavg < segsecs):
                                gcheck = True
                    else:
                        gcheck = False
                    logging.debug('GCHECK:' + str(gcheck))
                    # Check per live mode type:
                    if gcheck:
                        goup = 0
                        if live:
                            if lowlatency:
                                if(remainsegms == 0 and
                                   round(delayavg, 1) == segsecs):
                                        goup = 1
                            elif(delayavg < delaytogoup and delays[0] and
                                 delays[-1] < delaytogoup):
                                    goup = 1
                        elif(delayavg < delaytogoup and delays[0] and
                             delays[-1] < delaytogoup):
                                    goup = 1
                        if goup:
                            sys.stdout.flush()
                            sys.stdout.write('\rSwitching to' +
                                             ' higher video quality...')
                            vid += 1
                            if otf:
                                initvurl = videodata[vid][0].text
                                initvurl += videodata[vid][1][0].get(
                                                                    'sourceURL')
                                initv = session.get(initvurl).content
                                logging.debug('Initurl' + initvurl)

                            log_(("UP", vid, remainsegms, mindelay,
                                 ffmuxerdelay, delaytogoup, truedelays,
                                 truedelayavg, basedelays, basedelayavg, delays,
                                 delayavg, selectedbandwidth[1],
                                 nextbandwidth[1], minbandavg[1],
                                 minbandlast[1], bandslastavg[1],
                                 videodata[vid][0].text))
                    if not lowlatency and live:
                        sleepsecs = max(round((segsecs) - delays[-1], 4), 0)
                        logging.debug("Sleeping %s seconds..." % sleepsecs)
                        time.sleep(sleepsecs)
            # End While -
    sys.stdout.flush()
    os.closerange(3, 100)
    os.remove('/tmp/dash2.0.pid')
