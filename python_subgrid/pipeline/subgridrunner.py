#!/usr/bin/env python

"""
subgrid model runner
"""
import logging
import itertools
import argparse

from mmi import send_array, recv_array
from zmq.eventloop import ioloop
import zmq
import zmq.eventloop.zmqstream

import python_subgrid.plotting
import python_subgrid.wrapper

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
# ^^^ No, no, this should go in the main(). Everything that imports this gets
# these settings. TODO

ioloop.install()
# TODO: ^^^ also do this in the main()?


INITVARS = {'FlowElem_xcc', 'FlowElem_ycc', 'FlowElemContour_x',
            'FlowElemContour_y', 'dx', 'nmax', 'mmax',
            'mbndry', 'nbndry', 'ip', 'jp', 'nodm', 'nodn', 'nodk', 'nod_type',
            'dps', 'x0p', 'y0p', 'x1p', 'y1p', 'dxp', 'dyp', 'wkt',
            'imaxk', 'jmaxk', 'dmax', 'imax', 'jmax'}
OUTPUTVARS = ['s1']


def parse_args():
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        '-p', '--publishport', dest='publish_port',
        help='publishing port (port that publishes model results)',
        type=int,
        default=5556)
    argparser.add_argument(
        '-r', '--replyport', dest='reply_port',
        help='reply port (port which responds to requests)',
        type=int,
        default=5557)
    argparser.add_argument(
        '-n', '--interval', dest='interval',
        help='publishing results every [n] tiemsteps',
        type=int,
        default=1)
    argparser.add_argument(
        '-o', '--outputvariables', dest='outputvariables',
        metavar='O',
        nargs='*',
        help='variables to be published',
        default=OUTPUTVARS)
    argparser.add_argument(
        '-g', '--global', dest='globalvariables',
        metavar='G',
        nargs='*',
        help=('variables that can be send back to a reply ' +
              '(not changed during run)'),
        default=INITVARS)
    argparser.add_argument(
        '-c', '--config', dest='config',
        help='configuration file',
        default=None)
    argparser.add_argument(
        'ini',
        help='model configuration file')
    argparser.add_argument(
        "-s", "--serialization",
        dest="serialization protocol (numpy, json, bytes)",
        default="numpy")
    return argparser.parse_args()


# see or an in memory numpy message:
# http://zeromq.github.io/pyzmq/serialization.html


def process_incoming(subgrid, poller, rep, pull, data):
    """
    process incoming messages

    data is a dict with several arrays
    """
    # Check for new messages
    items = poller.poll(100)
    for sock, n in items:
        for i in range(n):
            A, metadata = recv_array(sock)
            logger.info("got metadata: %s", metadata)
            if metadata.get("action") == "send grid":
                logger.info("sending grid")
                # temporary implementation
                sock.send_pyobj(data)
            elif "action" in metadata:
                logger.info("found action applying update")
                # TODO: support same operators as MPI_ops here....,
                # TODO: reduce before apply
                action = metadata['action']
                arr = subgrid.get_nd(metadata['name'], sliced=True)
                S = tuple(slice(*x) for x in action['slice'])
                print(repr(arr[S]))
                if action['operator'] == 'setitem':
                    arr[S] = data
                elif action['operator'] == 'add':
                    arr[S] += data

            else:
                logger.warn("got message from unknown socket {}".format(sock))
    else:
        logger.info("No incoming data")


if __name__ == '__main__':

    arguments = parse_args()

    # make a socket that replies to message with the grid

    # You probably want to read:
    # http://zguide.zeromq.org/page:all

    context = zmq.Context()
    # Socket to handle init data
    rep = context.socket(zmq.REP)
    rep.bind(
        "tcp://*:{port}".format(port=5556)
    )
    pull = context.socket(zmq.PULL)
    pull.connect(
        "tcp://localhost:{port}".format(port=5557)
    )
    # for sending model messages
    pub = context.socket(zmq.PUB)
    pub.bind(
        "tcp://*:{port}".format(port=5558)
    )

    poller = zmq.Poller()
    poller.register(rep, zmq.POLLIN)
    poller.register(pull, zmq.POLLIN)

    python_subgrid.wrapper.logger.setLevel(logging.WARN)

    # for replying to grid requests
    with python_subgrid.wrapper.SubgridWrapper(mdu=arguments.ini) as subgrid:
        subgrid.initmodel()

        # Start a reply process in the background, with variables available
        # after initialization, sent all at once as py_obj
        data = {
            var: subgrid.get_nd(var, sliced=True)
            for var
            in arguments.globalvariables
        }
        # add the quad_grid for easy plotting
        data["quad_grid"] = python_subgrid.plotting.make_quad_grid(subgrid)
        process_incoming(subgrid, poller, rep, pull, data)

        # Keep on counting indefinitely
        counter = itertools.count()

        for i in counter:

            # Any requests?
            process_incoming(subgrid, poller, rep, pull, data)

            # Calculate
            subgrid.update(-1)

            # check counter
            if (i % arguments.interval):
                continue

            for key in arguments.outputvariables:
                value = subgrid.get_nd(key, sliced=True)
                metadata = {'name': key, 'iteration': i}
                # 4ms for 1M doubles
                logger.info("sending {}".format(metadata))
                send_array(pub, value, metadata=metadata)
