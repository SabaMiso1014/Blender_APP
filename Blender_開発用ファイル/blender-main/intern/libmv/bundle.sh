#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later

if [ "x$1" = "x--i-really-know-what-im-doing" ] ; then
  echo Proceeding as requested by command line ...
else
  echo "*** Please run again with --i-really-know-what-im-doing ..."
  exit 1
fi

BRANCH="main"

# repo="https://projects.blender.org/blender/libmv.git"
repo="/home/sergey/Developer/libmv"
tmp=`mktemp -d`

git clone -b $BRANCH $repo $tmp/libmv

git --git-dir $tmp/libmv/.git --work-tree $tmp/libmv log -n 50 > ChangeLog

find libmv -type f -exec rm -rf {} \;
find third_party -type f -exec rm -rf {} \;

cat "files.txt" | while read f; do
  mkdir -p `dirname $f`
  cp $tmp/libmv/src/$f $f
done

rm -rf $tmp

sources=`find ./libmv -type f -iname '*.cc' -or -iname '*.cpp' -or -iname '*.c' | grep -v _test.cc | grep -v test_data_sets | sed -r 's/^\.\//    /' | sort -d`
headers=`find ./libmv -type f -iname '*.h' | grep -v test_data_sets | sed -r 's/^\.\//    /' | sort -d`

third_sources=`find ./third_party -type f -iname '*.cc' -or -iname '*.cpp' -or -iname '*.c' | sed -r 's/^\.\//    /' | sort -d`
third_headers=`find ./third_party -type f -iname '*.h' | sed -r 's/^\.\//    /' | sort -d`

tests=`find ./libmv -type f -iname '*_test.cc' | sort -d | awk ' { name=gensub(".*/([A-Za-z_]+)_test.cc", "\\\\1", "g", $1); printf("    blender_add_test_executable(\"libmv_%s\" \"%s\" \"\${INC}\" \"\${INC_SYS}\" \"libmv_test_dataset;bf_intern_libmv;extern_ceres\")\n", name, $1) } '`

src_dir=`find ./libmv -type f -iname '*.cc' -exec dirname {} \; -or -iname '*.cpp' -exec dirname {} \; -or -iname '*.c' -exec dirname {} \; | sed -r 's/^\.\//    /' | sort -d | uniq`
src_third_dir=`find ./third_party -type f -iname '*.cc' -exec dirname {} \; -or -iname '*.cpp' -exec dirname {} \; -or -iname '*.c' -exec dirname {} \;  | sed -r 's/^\.\//    /'  | sort -d | uniq`
src=""
win_src=""
for x in $src_dir $src_third_dir; do
  t=""

  if stat $x/*.cpp > /dev/null 2>&1; then
    t="    src += env.Glob('`echo $x'/*.cpp'`')"
  fi

  if stat $x/*.c > /dev/null 2>&1; then
    if [ -z "$t" ]; then
      t="    src += env.Glob('`echo $x'/*.c'`')"
    else
      t="$t + env.Glob('`echo $x'/*.c'`')"
    fi
  fi

  if stat $x/*.cc > /dev/null 2>&1; then
    if [ -z "$t" ]; then
      t="    src += env.Glob('`echo $x'/*.cc'`')"
    else
      t="$t + env.Glob('`echo $x'/*.cc'`')"
    fi
  fi

  if test `echo $x | grep -c "windows\|gflags" ` -eq 0; then
    if [ -z "$src" ]; then
      src=$t
    else
      src=`echo "$src\n$t"`
    fi
  else
    if [ -z "$win_src" ]; then
      win_src=`echo "    $t"`
    else
      win_src=`echo "$win_src\n    $t"`
    fi
  fi
done

cat > CMakeLists.txt << EOF
# ***** BEGIN GPL LICENSE BLOCK *****
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# The Original Code is Copyright (C) 2011, Blender Foundation
# All rights reserved.
# ***** END GPL LICENSE BLOCK *****

# NOTE: This file is automatically generated by bundle.sh script
#       If you're doing changes in this file, please update template
#       in that script too

set(INC
  .
)

set(INC_SYS
)

set(SRC
  libmv-capi.h
)

set(LIB

)

if(WITH_LIBMV)
  if(WIN32)
    add_definitions(-D_USE_MATH_DEFINES)
  endif()
  add_definitions(\${GFLAGS_DEFINES})
  add_definitions(\${GLOG_DEFINES})
  add_definitions(-DLIBMV_GFLAGS_NAMESPACE=\${GFLAGS_NAMESPACE})

  list(APPEND INC
    \${GFLAGS_INCLUDE_DIRS}
    \${GLOG_INCLUDE_DIRS}
    ../guardedalloc
  )

  list(APPEND INC_SYS
    \${EIGEN3_INCLUDE_DIRS}
    \${PNG_INCLUDE_DIRS}
    \${ZLIB_INCLUDE_DIRS}
    ../../extern/ceres/include
    ../../extern/ceres/config
  )

  list(APPEND LIB
    extern_ceres

    \${GLOG_LIBRARIES}
    \${GFLAGS_LIBRARIES}
    \${PNG_LIBRARIES}
  )

  add_definitions(
    -DWITH_LIBMV_GUARDED_ALLOC
    -DLIBMV_NO_FAST_DETECTOR=
  )

  list(APPEND SRC
    intern/autotrack.cc
    intern/camera_intrinsics.cc
    intern/detector.cc
    intern/frame_accessor.cc
    intern/homography.cc
    intern/image.cc
    intern/logging.cc
    intern/reconstruction.cc
    intern/track_region.cc
    intern/tracks.cc
    intern/tracksN.cc
${sources}
${third_sources}

    intern/autotrack.h
    intern/camera_intrinsics.h
    intern/detector.h
    intern/frame_accessor.h
    intern/homography.h
    intern/image.h
    intern/logging.h
    intern/reconstruction.h
    intern/region.h
    intern/track_region.h
    intern/tracks.h
    intern/tracksN.h
    intern/utildefines.h
${headers}

${third_headers}
  )


  if(WITH_GTESTS)
    include(GTestTesting)

    blender_add_lib(libmv_test_dataset "./libmv/multiview/test_data_sets.cc" "\${INC}" "\${INC_SYS}" "")

${tests}
  endif()
else()
  list(APPEND SRC
    intern/stub.cc
  )
endif()

blender_add_lib(bf_intern_libmv "\${SRC}" "\${INC}" "\${INC_SYS}" "\${LIB}")
EOF
