"""
Copyright (C) 2021 Alexander G. Ororbia II - All Rights Reserved
You may use, distribute and modify this code under the
terms of the BSD 3-clause license.

You should have received a copy of the BSD 3-clause license with
this file. If not, please write to: ago@cs.rit.edu
"""

import os
import sys
import copy
#from config import Config
import tensorflow as tf
import numpy as np

from ngclearn.engine.nodes.snode import SNode
from ngclearn.engine.nodes.enode import ENode
from ngclearn.engine.ngc_graph import NGCGraph

from ngclearn.engine.nodes.fnode import FNode
from ngclearn.engine.proj_graph import ProjectionGraph

class GNCN_t1:
    """
    Structure for constructing the model proposed in:

    Rao, Rajesh PN, and Dana H. Ballard. "Predictive coding in the visual
    cortex: a functional interpretation of some extra-classical receptive-field
    effects." Nature neuroscience 2.1 (1999): 79-87.

    Note this model includes the Laplacian prior to induce some level of sparsity
    in the latent activities.

    This model, under the NGC computational framework, is referred to as
    the GNCN-t1/Rao, according to the naming convention in (Ororbia & Kifer 2022).

    Arguments:
    args: a Config dictionary containing necessary meta-parameters for the GNCN-t1

    NOTE - args should contain values for the following:
    z_top_dim: # of latent variables in layer z3 (top-most layer)
    z_dim: # of latent variables in layers z1 and z2
    x_dim: # of latent variables in layer z0 or sensory x
    seed: number to control determinism of weight initialization
    wght_sd: standard deviation of Gaussian initialization of weights
    beta: latent state update factor
    leak: strength of the leak variable in the latent states
    lmbda: strength of the Laplacian prior applied over latent state activities
    K: # of steps to take when conducting iterative inference/settling
    act_fx: activation function for layers z1, z2, and z3
    out_fx: activation function for layer mu0 (prediction of z0) (Default: sigmoid)

    @author: Alexander Ororbia
    """
    def __init__(self, args):
        self.args = args

        z_top_dim = int(self.args.getArg("z_top_dim"))
        z_dim = int(self.args.getArg("z_dim"))
        x_dim = int(self.args.getArg("x_dim"))

        seed = int(self.args.getArg("seed")) #69
        beta = float(self.args.getArg("beta"))
        K = int(self.args.getArg("K"))
        act_fx = self.args.getArg("act_fx") #"tanh"
        out_fx = "sigmoid"
        if self.args.hasArg("out_fx") == True:
            out_fx = self.args.getArg("out_fx")
        leak = float(self.args.getArg("leak")) #0.0

        # set up state integration function
        integrate_cfg = {"integrate_type" : "euler", "use_dfx" : True}
        lmbda = float(self.args.getArg("lmbda")) #0.0002
        prior_cfg = {"prior_type" : "laplace", "lambda" : lmbda}
        use_mod_factor = False #(self.args.getArg("use_mod_factor").lower() == 'true')

        # set up system nodes
        z3 = SNode(name="z3", dim=z_top_dim, beta=beta, leak=leak, act_fx=act_fx,
                   integrate_kernel=integrate_cfg, prior_kernel=prior_cfg)
        mu2 = SNode(name="mu2", dim=z_dim, act_fx="identity", zeta=0.0)
        e2 = ENode(name="e2", dim=z_dim)
        z2 = SNode(name="z2", dim=z_dim, beta=beta, leak=leak, act_fx=act_fx,
                   integrate_kernel=integrate_cfg, prior_kernel=prior_cfg)
        mu1 = SNode(name="mu1", dim=z_dim, act_fx="identity", zeta=0.0)
        e1 = ENode(name="e1", dim=z_dim)
        z1 = SNode(name="z1", dim=z_dim, beta=beta, leak=leak, act_fx=act_fx,
                   integrate_kernel=integrate_cfg, prior_kernel=prior_cfg)#, lateral_kernel=lateral_cfg)
        mu0 = SNode(name="mu0", dim=x_dim, act_fx=out_fx, zeta=0.0)
        e0 = ENode(name="e0", dim=x_dim)
        z0 = SNode(name="z0", dim=x_dim)

        # create cable wiring scheme relating nodes to one another
        wght_sd = float(self.args.getArg("wght_sd")) #0.025 #0.05 # 0.055
        dcable_cfg = {"type": "dense", "has_bias": False,
                      "init" : ("gaussian",wght_sd), "seed" : seed}
        pos_scable_cfg = {"type": "simple", "coeff": 1.0}
        neg_scable_cfg = {"type": "simple", "coeff": -1.0}

        z3_mu2 = z3.wire_to(mu2, src_var="phi(z)", dest_var="dz", cable_kernel=dcable_cfg)
        mu2.wire_to(e2, src_var="phi(z)", dest_var="pred_mu", cable_kernel=pos_scable_cfg)
        z2.wire_to(e2, src_var="z", dest_var="pred_targ", cable_kernel=pos_scable_cfg)
        e2.wire_to(z3, src_var="phi(z)", dest_var="dz", mirror_path_kernel=(z3_mu2,"symm_tied")) #anti_symm_tied
        #e2.use_mod_factor = use_mod_factor
        e2.wire_to(z2, src_var="phi(z)", dest_var="dz", cable_kernel=neg_scable_cfg)

        z2_mu1 = z2.wire_to(mu1, src_var="phi(z)", dest_var="dz", cable_kernel=dcable_cfg)
        mu1.wire_to(e1, src_var="phi(z)", dest_var="pred_mu", cable_kernel=pos_scable_cfg)
        z1.wire_to(e1, src_var="z", dest_var="pred_targ", cable_kernel=pos_scable_cfg)
        e1.wire_to(z2, src_var="phi(z)", dest_var="dz", mirror_path_kernel=(z2_mu1,"symm_tied")) #anti_symm_tied
        #e1.use_mod_factor = use_mod_factor
        e1.wire_to(z1, src_var="phi(z)", dest_var="dz", cable_kernel=neg_scable_cfg)

        z1_mu0 = z1.wire_to(mu0, src_var="phi(z)", dest_var="dz", cable_kernel=dcable_cfg)
        mu0.wire_to(e0, src_var="phi(z)", dest_var="pred_mu", cable_kernel=pos_scable_cfg)
        z0.wire_to(e0, src_var="phi(z)", dest_var="pred_targ", cable_kernel=pos_scable_cfg)
        e0.wire_to(z1, src_var="phi(z)", dest_var="dz", mirror_path_kernel=(z1_mu0,"symm_tied")) #anti_symm_tied
        e0.wire_to(z0, src_var="phi(z)", dest_var="dz", cable_kernel=neg_scable_cfg)

        # set up update rules and make relevant edges aware of these
        z3_mu2.set_update_rule(preact=(z3,"phi(z)"), postact=(e2,"phi(z)"))
        z2_mu1.set_update_rule(preact=(z2,"phi(z)"), postact=(e1,"phi(z)"))
        z1_mu0.set_update_rule(preact=(z1,"phi(z)"), postact=(e0,"phi(z)"))

        # Set up graph - execution cycle/order
        print(" > Constructing NGC graph")
        ngc_model = NGCGraph(K=K)
        ngc_model.proj_update_mag = -1.0 #-1.0
        ngc_model.proj_weight_mag = 1.0
        ngc_model.set_cycle(nodes=[z3,z2,z1,z0])
        ngc_model.set_cycle(nodes=[mu2,mu1,mu0])
        ngc_model.set_cycle(nodes=[e2,e1,e0])
        ngc_model.apply_constraints()
        self.ngc_model = ngc_model

        # build this NGC model's sampling graph
        z3_dim = ngc_model.getNode("z3").dim
        z2_dim = ngc_model.getNode("z2").dim
        z1_dim = ngc_model.getNode("z1").dim
        z0_dim = ngc_model.getNode("z0").dim
        # Set up complementary sampling graph to use in conjunction w/ NGC-graph
        s3 = FNode(name="s3", dim=z3_dim, act_fx=act_fx)
        s2 = FNode(name="s2", dim=z2_dim, act_fx=act_fx)
        s1 = FNode(name="s1", dim=z1_dim, act_fx=act_fx)
        s0 = FNode(name="s0", dim=z0_dim, act_fx=out_fx)
        s3_s2 = s3.wire_to(s2, src_var="phi(z)", dest_var="dz", point_to_path=z3_mu2)
        s2_s1 = s2.wire_to(s1, src_var="phi(z)", dest_var="dz", point_to_path=z2_mu1)
        s1_s0 = s1.wire_to(s0, src_var="phi(z)", dest_var="dz", point_to_path=z1_mu0)
        sampler = ProjectionGraph()
        sampler.set_cycle(nodes=[s3,s2,s1,s0])
        self.ngc_sampler = sampler

    def project(self, z_sample):
        """
        Run projection scheme to get a sample of the underlying directed
        generative model given the clamped variable *z_sample*

        Arguments:
        z_sample: the input noise sample to project through the NGC graph

        Returns:
        x_sample (sample(s) of the underlying generative model)
        """
        readouts = self.ngc_sampler.project(
                        clamped_vars=[("s3",tf.cast(z_sample,dtype=tf.float32))],
                        readout_vars=[("s0","phi(z)")]
                    )
        x_sample = readouts[0][2]
        return x_sample

    def settle(self, x):
        """
        Run an iterative settling process to find latent states given clamped
        input and output variables

        Arguments:
        x: sensory input to reconstruct/predict

        Returns:
        x_hat (predicted x)
        """
        readouts = self.ngc_model.settle(
                        clamped_vars=[("z0", x)],
                        readout_vars=[("mu0","phi(z)"),("mu1","phi(z)"),("mu2","phi(z)")]
                    )
        x_hat = readouts[0][2]
        return x_hat

    def calc_updates(self, avg_update=True):
        """
        Calculate adjustments to parameters under this given model and its
        current internal state values

        Returns:
        delta, a list of synaptic matrix updates (that follow order of .theta)
        """
        Ns = self.ngc_model.extract("z0","phi(z)").shape[0]
        delta = self.ngc_model.calc_updates()
        if avg_update is True:
            for p in range(len(delta)):
                delta[p] = delta[p] * (1.0/(Ns * 1.0))
        return delta

    def update(self, x, avg_update=True):
        """
        Updates synaptic parameters/connections given sensory input

        Arguments:
        x: a sensory sample or batch of sensory samples
        """
        self.settle(x)
        delta = self.calc_updates(avg_update=avg_update)
        self.opt.apply_gradients(zip(delta, self.ngc_model.theta))
        self.ngc_model.apply_constraints()

    def clear(self):
        """Clears the states/values of the stateful nodes in this NGC system"""
        self.ngc_model.clear()
        self.ngc_sampler.clear()

    def print_norms(self):
        """Prints the Frobenius norms of each parameter of this system"""
        str = ""
        for param in self.ngc_model.theta:
            str = "{} | {} : {}".format(str, param.name, tf.norm(param,ord=2))
        #str = "{}\n".format(str)
        return str

    def set_weights(self, source, tau=0.005): #0.001):
        """
        Deep copies weight variables of another model (of the same exact type)
        into this model's weight variables
        """
        #self.param_var = copy.deepcopy(source.param_var)
        if tau >= 0.0:
            for l in range(0, len(self.ngc_model.theta)):
                self.ngc_model.theta[l].assign( self.ngc_model.theta[l] * (1 - tau) + source.ngc_model.theta[l] * tau )
        else:
            for l in range(0, len(self.ngc_model.theta)):
                self.ngc_model.theta[l].assign( source.ngc_model.theta[l] )