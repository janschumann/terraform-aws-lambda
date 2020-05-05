# Generates a content hash of the source_path, which is used to determine if
# the Lambda code has changed, ignoring file modification and access times.
#
# Outputs a filename and a command to run if the archive needs to be built.

import datetime
import errno
import hashlib
import json
import os
import sys


def abort(message):
    """
    Exits with an error message.

    """

    sys.stderr.write(message + '\n')
    sys.exit(1)


def delete_old_archives():
    """
    Deletes previously created archives.

    """

    now = datetime.datetime.now()
    delete_older_than = now - datetime.timedelta(days=7)

    for name in os.listdir('builds'):
        if name.endswith('.zip'):
            try:
                file_modified = datetime.datetime.fromtimestamp(
                    os.path.getmtime(name)
                )
                if file_modified < delete_older_than:
                    os.remove(name)
            except OSError as error:
                if error.errno == errno.ENOENT:
                    # Ignore "not found" errors as they are probably race
                    # conditions between multiple usages of this module.
                    pass
                else:
                    raise


def list_files(top_path):
    """
    Returns a sorted list of all files in a directory.

    """

    results = []

    for root, dirs, files in os.walk(top_path):
        for file_name in files:
            results.append(os.path.join(root, file_name))

    results.sort()
    return results


def generate_content_hash(source_paths):
    """
    Generate a content hash of the source paths.

    """

    sha256 = hashlib.sha256()

    for source_path in source_paths:
        if os.path.isdir(source_path):
            source_dir = source_path
            for source_file in list_files(source_dir):
                update_hash(sha256, source_dir, source_file)
        else:
            source_dir = os.path.dirname(source_path)
            source_file = source_path
            update_hash(sha256, source_dir, source_file)

    return sha256


def update_hash(hash_obj, file_root, file_path):
    """
    Update a hashlib object with the relative path and contents of a file.

    """

    relative_path = os.path.relpath(file_path, file_root)
    hash_obj.update(relative_path.encode())

    with open(file_path, 'rb') as open_file:
        while True:
            data = open_file.read(1024)
            if not data:
                break
            hash_obj.update(data)


def get_abs_dirname(p):
    """
    Returns an absolute dirname, even if a file has been provided

    """

    p = os.path.abspath(p)
    if os.path.isfile(p):
        return os.path.basename(p)

    return p


def build_relative_path(a, b):
    """
    Returns a relative path of a compared to b

    """

    aa = get_abs_dirname(a)
    ba = get_abs_dirname(b)
    if aa == ba:
        # same directory: return the given path
        return a

    aelem = aa.split('/')
    belem = ba.split('/')
    selem = []
    for e in aelem:
        if e != belem[len(selem)]:
            break

        selem.append(e)

    if len(selem) < 2:
        # only the first / is the same => there is no relative path
        # so we use the absolute path
        return aa

    # calculate the remaining path elements of b
    s = '/'.join(selem)
    rem = ba.replace(s, "")
    rem = rem.replace('/', '', 1)
    relem = rem.split('/')

    # go back
    rel_path = ""
    for e in relem:
        rel_path = '{}../'.format(rel_path)

    return '{}{}'.format(rel_path, a)


# Parse the query.
query = json.load(sys.stdin)
build_command = query['build_command']
build_paths = json.loads(query['build_paths'])
module_relpath = query['module_relpath']
runtime = query['runtime']
source_path = os.path.abspath(query['source_path'])

# Validate the query.
if not source_path:
    abort('source_path must be set.')

# use relative paths for hash calculation
hash_dirs = []
final_source_path = build_relative_path(query['source_path'], module_relpath)
for dir in build_paths:
    hash_dirs.append(build_relative_path(dir, module_relpath))

# distinct list (for the case that build script is in the same dir as the function)
hash_dirs = [final_source_path] + hash_dirs
hash_dirs = list(set(hash_dirs))

# Change working directory to the module path
# so references to build.py will work.
os.chdir(module_relpath)

# Generate a hash based on file names and content. Also use the
# runtime value, build command, and content of the build paths
# because they can have an effect on the resulting archive.
content_hash = generate_content_hash(hash_dirs)
content_hash.update(runtime.encode())
content_hash.update(build_command.encode())

# Generate a unique filename based on the hash.
filename = 'builds/{content_hash}.zip'.format(
    content_hash=content_hash.hexdigest(),
)

# Replace variables in the build command with calculated values.
replacements = {
    '$filename': filename,
    '$runtime': runtime,
    '$source': final_source_path,
}
for old, new in replacements.items():
    build_command = build_command.replace(old, new)

# Delete previous archives.
delete_old_archives()

# Output the result to Terraform.
json.dump({
    'filename': filename,
    'build_command': build_command,
}, sys.stdout, indent=2)
sys.stdout.write('\n')
