#! /usr/bin/env python
# -*- coding: utf-8 -*-
__author__ = 'lihe <imanux@sina.com>'
__date__ = '11/16 22:17'
__description__ = '''
'''
import os
import sys
import json
from urllib.parse import urljoin, urlencode, quote
import re

app_root = '/'.join(os.path.abspath(__file__).split('/')[:-2])
sys.path.append(app_root)

import wget
import click
from logzero import logger as zlog
from izen.crawler import AsyncCrawler, UA
from izen import helper, crawler
from izen.prettify import ColorPrint, Prettify
from music.metas import Metas
from music.site_header import SonimeiHeaders, NeteaseHeaders

get_headers = crawler.ParseHeaderFromFile('netease.txt', use_cookies=False).headers

SITES = {
    'qq': 'qq',
}

PRETTY = Prettify({
    'cc.symbols': ' ,,,, ,,,,,,,,ﴖ,,,,,,,♪,'
})
CP = ColorPrint()
local_musics = []


class NE(object):
    def __init__(self, log_level=10):
        self.home = 'https://music.163.com/'
        self.ac = AsyncCrawler(
            site_init_url=self.home,
            base_dir=os.path.expanduser('~/.crawler'),
            timeout=10,
            log_level=log_level,
        )
        self.ac.headers['get'] = NeteaseHeaders.get

    def do_get(self, url):
        doc = self.ac.bs4get(url)
        album_doc = doc.find_all(class_='des s-fc4')[-1]
        album = album_doc.a.text
        return album


class YiTing(object):
    def __init__(self, site='qq', use_cache=True, log_level=10):
        self.home = 'http://music.sonimei.cn/'
        self.ac = AsyncCrawler(
            site_init_url=self.home,
            base_dir=os.path.expanduser('~/.crawler'),
            timeout=10,
            log_level=log_level,
        )
        self.use_cache = use_cache
        if site == 'netease':
            self.site_netease = NE(log_level)
        self.ac.headers['post'] = SonimeiHeaders.post
        self.site = site
        self.save_dir = os.path.expanduser('~/Music/favor/')
        self.log_level = log_level
        self._spawn()

    def _spawn(self):
        self.ac.headers['Host'] = self.ac.domain

    def is_file_exist(self, song_name):
        """TODO: use sqlite for song names"""
        song_name = song_name.split('-')[-1].split('.')[0]
        similar = []
        for song in local_musics:
            song_ = '.'.join(song.split('.')[:-1])
            if song_name in [song_, *song_.split('-')]:
                similar.append(song)

        return similar

    def is_file_ok(self, song_name):
        song_pth = os.path.join(self.save_dir, song_name)
        if song_pth[-4:] != '.mp3':
            song_pth += '.mp3'

        if helper.is_file_ok(song_pth):
            has_pic, song_id3 = Metas(True).get_song_meta(song_pth)
            return has_pic, song_pth
        return False, None

    @staticmethod
    def get_best_match(songs, name, author):
        best_match = []
        songs_got = []
        for i, song in enumerate(songs):
            _title = '{}-{}'.format(song['author'], song['title'])
            url = song['url']
            songs_got.append('{} {}'.format(_title, url))

            b = False or author in song['author'] or song['author'] in author
            b = b and (name in song['title'] or song['title'] in name)
            if b:
                best_match.append('{} {}'.format(_title, url))

        keys = ['demo', 'live']
        for k in keys:
            if len(best_match) == 1:
                return best_match[0]
            elif not best_match:
                return songs_got
            best_match = [x for x in best_match if k not in x]

        return best_match

    def search_it(self, name, page=1):
        form = {
            'filter': 'name',
            'type': self.site,
            'page': page,
            'input': name,
        }
        doc = self.ac.bs4post(self.home, data=form, show_log=True, use_cache=self.use_cache)
        songs = doc['data']
        if not songs:
            zlog.warning('[{}] matched nothing.'.format(name))
            os._exit(0)

        return songs

    def parse_song(self, dat):
        if isinstance(dat, str):
            dat = json.loads(dat)
        url = dat['url']
        if self.site == 'qq':
            song_extension = url.split('?')[0].split('.')[-1]
        else:
            # elif self.site == 'netease':
            #     song_extension = url.split('.')[-1]
            # else:
            song_extension = 'mp3'
        return song_extension

    def get_song_album(self, dat):
        """
        TALB
        """
        if self.site == 'qq':
            return self.get_qq_album(dat)
        elif self.site == 'netease':
            return self.get_netease_album(dat)
        else:
            return ''

    def get_netease_album(self, dat):
        link = urljoin('https://music.163.com', dat['link'].split('#')[1])
        album = self.site_netease.do_get(link)
        return album

    def get_qq_album(self, dat):
        doc = self.ac.bs4get(dat['link'], use_cache=self.use_cache)
        _pg = re.compile('g_SongData = *')
        rs = doc.find(string=_pg)
        rs = rs.split(' = ')
        detail = json.loads(rs[1].strip()[:-1])
        return detail['albumname']

    @staticmethod
    def download(src, save_to):
        if helper.is_file_ok(save_to):
            zlog.debug('{} is downloaded.'.format(save_to))
        else:
            zlog.debug('try get {}'.format(save_to))
            wget.download(src, out=save_to)
            # wget output end without new line
            print()
            zlog.info('downloaded {}'.format(helper.G.format(save_to)))

    def save_song(self, song):
        extension = self.parse_song(song)
        title = song['author'] + '-' + song['title']
        song_pth = os.path.join(self.save_dir, '{}.{}'.format(title, extension))
        pic_pth = os.path.join(self.ac.cache['site_media'], title + '.jpg')
        try:
            self.download(song['url'], song_pth)
            self.download(song['pic'], pic_pth)
        except Exception:
            zlog.error('failed {}'.format(song))
            os._exit(-1)
        self.update_song(song, song_pth, pic_pth)

    def update_song(self, song, song_pth, pic_pth):
        tags = ['TIT2', 'TPE1', 'TALB']
        site_dat = {'TPE1': song['author'].strip(), 'TIT2': song['title'].strip()}
        has_pic, song_id3 = Metas(self.log_level <= 10).get_song_meta(song_pth)

        id3_same = True
        # skip TALB
        for tag in tags[:-1]:
            if site_dat[tag] != song_id3.get(tag):
                zlog.debug('Not Matched: site({}) != id3({})'.format(site_dat[tag], song_id3.get(tag)))
                id3_same = False
                # id3_same = id3_same and site_dat[tag] == song_id3[tag]
        if not has_pic:
            site_dat['APIC'] = pic_pth
            id3_same = False

        if not song_id3.get('TALB') or not id3_same:
            site_dat['TALB'] = self.get_song_album(song)

        if not id3_same:
            CP.G('update {}'.format(site_dat))
            Metas(self.log_level <= 10).update_song_meta(song_pth, site_dat)


def scan_update_id3():
    save_dir = os.path.expanduser('~/Music/favor/')
    songs = helper.walk_dir_with_filter(save_dir, prefix=['.DS_Store'])
    songs = [x.split('/')[-1] for x in songs]
    return songs


def fmt_help(*args, show_more=True):
    desc = helper.G.format(args[0])
    if show_more:
        if len(args) > 1:
            args = list(args[1:])
            args.insert(0, '[OPT] ')
            usage = ''.join([helper.B.format(x) for x in args])
            desc = '{}\n{}'.format(desc, usage)
    return desc


@click.command(
    context_settings=dict(
        help_option_names=['-h', '--help'],
        terminal_width=200,
    ),
)
@click.option('--name', '-n',
              help=fmt_help('the name of song/songs', '-n <song1#song2#...>'))
@click.option('--site', '-s',
              default='qq',
              help=fmt_help('site to search', '-s <qq/netease>'))
@click.option('--multiple', '-m',
              is_flag=True,
              help=fmt_help('download multiple songs', '-m'))
@click.option('--no_cache', '-nc',
              is_flag=True,
              help=fmt_help('use no cache', '-nc'))
@click.option('--log_level', '-l',
              default=2,
              type=click.IntRange(1, 5),
              help=fmt_help('set log level', '-l <1~5>'))
@click.option('--scan_mode', '-scan',
              is_flag=True,
              help=fmt_help('scan all songs and add id3 info', '-scan'))
def run(name, site, multiple, no_cache, log_level, scan_mode):
    """ a lovely script use sonimei search qq/netease songs """
    global local_musics
    scanned_songs = []
    local_musics = scan_update_id3()
    if scan_mode:
        scanned_songs = local_musics
    if not name and not scanned_songs:
        return

    if not scanned_songs:
        scanned_songs = [x for x in name.split('#')]

    yt = YiTing(site, not no_cache, log_level=log_level * 10)
    for i, name in enumerate(scanned_songs):
        songs_store = {}
        page = 1
        CP.F(PRETTY.symbols['right'], 'processing/total: {}/{}'.format(i + 1, len(scanned_songs)))

        while True:
            if not scan_mode:
                cache = yt.is_file_exist(name)
                if cache:
                    CP.R('Found from local, (press s)still want search and download???')
                    c = helper.num_choice(
                        cache, default='q', valid_keys='s',
                        extra_hints='s-skip',
                    )
                    if c != 's':
                        break

            status, song_pth = yt.is_file_ok(name)
            if status:
                CP.G(PRETTY.symbols['music'], '[{}] is found and updated'.format(song_pth))
                break

            songs = songs_store.get(page)
            if not songs:
                zlog.info('from sonimei try: {}/{}/{}'.format(name, site, page))
                songs = yt.search_it(name, page=page)
                songs_store[page] = songs
            song_info = [x['author'] + '-' + x['title'] for x in songs]

            c = helper.num_choice(
                song_info, valid_keys='p,n,s', depth=page,
                extra_hints='n-next,p-pre,s-skip',
                clear_previous=True,
            )
            if isinstance(c, str):
                if c in 'qQ':
                    return
                if c in 'bp':
                    if page > 1:
                        page -= 1
                    continue
                if c == 'n':
                    page += 1
                    continue
                if c == 's':  # skip current song
                    break
            yt.save_song(songs[c])

            if not multiple:
                break


if __name__ == '__main__':
    run()
