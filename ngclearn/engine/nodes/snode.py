"""
Copyright (C) 2021 Alexander G. Ororbia II - All Rights Reserved
You may use, distribute and modify this code under the
terms of the BSD 3-clause license.

You should have received a copy of the BSD 3-clause license with
this file. If not, please write to: ago@cs.rit.edu
"""

import tensorflow as tf
import sys
import numpy as np
import copy
from ngclearn.engine.nodes.node import Node
from ngclearn.utils import transform_utils

class SNode(Node):
    """
        Rate-coded state node
    """
    def __init__(self, name, dim, beta=1.0, leak=0.0, zeta=1.0, act_fx="identity",
                 integrate_kernel=None, prior_kernel=None, lateral_kernel=None,
                 trace_kernel=None):
        node_type = "state"
        super().__init__(node_type, name, dim)
        self.use_dfx = False
        self.integrate_type = "euler" # euler, midpoint
        if integrate_kernel is not None:
            self.use_dfx = integrate_kernel.get("use_dfx")
            self.integrate_type = integrate_kernel.get("integrate_type")
        self.prior_type = None
        self.lbmda = 0.0
        if prior_kernel is not None:
            self.prior_type = prior_kernel.get("prior_type")
            self.lbmda = prior_kernel.get("lambda")

        fx, dfx = transform_utils.decide_fun(act_fx)
        self.fx = fx
        self.dfx = dfx
        self.n_winners = -1
        if "bkwta" in act_fx:
            self.n_winners = int(act_fx[act_fx.index("(")+1:act_fx.rindex(")")])

        # node meta-parameters
        self.beta = beta
        self.leak = leak
        self.zeta = zeta

        self.a = None
        if trace_kernel is not None:
            # (trace) filter parameters (for compatibility with spiking neuron models)
            self.tau = integrate_kernel.get("tau") #5.0 # filter time constant -- where dt (or T) = 0.001 (to model ms)
            self.dt = integrate_kernel.get("dt") #1.0 # integration time constant (ms)
            # derived settings that are a function of other spiking neuron settings
            self.a = np.exp(-self.dt/self.tau)

        self.build_tick()

    def check_correctness(self):
        is_correct = True
        for j in range(len(self.input_nodes)):
            n_j = self.input_nodes[j]
            cable_j = self.input_cables[j]
            dest_var_j = cable_j.out_var
            if dest_var_j != "dz":
                is_correct = False
                print("ERROR: Cable {0} mis-wires to {1}.{2} (can only be .dz)".format(cable_j.name, self.name, dest_var_j))
                break
        return is_correct

    ############################################################################
    # Signal Transmission Routines
    ############################################################################

    def step(self, skip_core_calc=False):
        z = self.stat.get("z")
        phi_z = self.stat.get("phi(z)")
        if self.is_clamped is False and skip_core_calc is False:

            for j in range(len(self.input_nodes)):
                n_j = self.input_nodes[j]
                cable_j = self.input_cables[j]
                dest_var_j = cable_j.out_var
                # print("Parent ",n_j.name)
                # print("     z = ",n_j.extract("z"))
                # print("phi(z) = ",n_j.extract("phi(z)"))
                tick_j = self.tick.get(dest_var_j)
                var_j = self.stat.get(dest_var_j) # get current value of component
                dz_j = cable_j.propagate(n_j)
                if tick_j > 0: #if var_j is not None:
                    var_j = var_j + dz_j
                else:
                    var_j = dz_j
                self.stat[dest_var_j] = var_j
                self.tick[dest_var_j] = self.tick[dest_var_j] + 1
            dz = self.stat.get("dz")
            # if self.V is not None: # apply lateral filtering connections in V
            #      dz = dz - tf.matmul(phi_z, self.V)
            if dz is None:
                dz = 0.0
            else:
                if self.use_dfx is True:
                    dz = dz * self.dfx(z)
            z_prior = 0.0
            if self.prior_type is not None:
                if self.lbmda > 0.0:
                    if self.prior_type == "laplace":
                        z_prior = -tf.math.sign(z) * self.lbmda
            if self.integrate_type == "euler":
                """
                Euler integration step (under NGC inference dynamics)

                Constants/meta-parameters:
                beta - strength of update to node state z
                leak - controls strength of leak variable/decay
                zeta - if set to 0 turns off recurrent carry-over of node's current state value
                prior(z) - distributional prior placed over z (such as kurtotic prior, e.g. Laplace/Cauchy)

                Dynamics Equation:
                z <- z * zeta + ( dz * beta - z * leak + prior(z) )
                """
                dz = dz - z * self.leak + z_prior
                z = z * self.zeta + dz * self.beta
            else:
                print("Error: Node {0} does not support {1} integration".format(self.name, self.integrate_type))
                sys.exit(1)
        # the post-activation function is computed always, even if pre-activation is clamped
        phi_z = None
        if self.n_winners > 0:
            #print("-------------")
            #print(self.name)
            #print("***************")
            #print(self.n_winners)
            #print(self.fx)
            #print("***************")
            phi_z = self.fx(z,K=self.n_winners)
        else:
            phi_z = self.fx(z)
        #phi_z = self.fx(z)
        self.stat["z"] = z
        self.stat["phi(z)"] = phi_z

        if self.a is not None:
            ##########################################################################
            # apply variable trace filters z_l(t) = (alpha * z_l(t))*(1−s`(t)) +s_l(t)
            phi_z = tf.add((phi_z * self.a) * (-Sz + 1.0), Sz)
            self.stat["phi(z)"] = phi_z
            ##########################################################################

        bmask = self.stat.get("mask")
        if bmask is not None: # applies mask to all component variables of this node
            if self.stat.get("dz") is not None:
                self.stat["dz"] = self.stat.get("dz") * bmask
            if self.stat.get("z") is not None:
                self.stat["z"] = self.stat.get("z") * bmask
            if self.stat.get("phi(z)") is not None:
                self.stat["phi(z)"] = self.stat.get("phi(z)") * bmask

        self.build_tick()