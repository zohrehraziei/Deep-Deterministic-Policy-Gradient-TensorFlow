# -*- coding: utf-8 -*-
"""
Created on Tue Mar 17 17:43:46 2020
Deep Deterministic Policy Gradients Method with Tensorflow

@author: raziei.z@husky.neu.edu
"""
# need replay buffer class
# use replay buffer to address the issue between samples generated on subsequent steps within an episode
# need class for target Q network  (a function of state and action) 
# we will use batch norm
# the policy is deterministic, so how to handle explore-exploit delimma? 
# answer: use stochastic policy to solve deterministic policy
# deterministic policy means to output the actual action instead of probability
# we need a way to bound action to env limit
# we have two actors and two critics networsks, a target for each
# has four NNs, two on-policy and two off policy
# update are soft for parameter of the two target networks - theta_prime = tau*theta + (1-tau)*theta_prime with tau<<1
# the target actor is just evaluation acotr plus some noise process (N)
# they use Ornstein Uhlenbeck -> need a class for noise
# so need claas for replay buffer (batch normalization), noise, actor, and critic

#https://github.com/openai/baselines/blob/master/baselines/ddpg/noise.py

import os
import numpy as np
import tensorflow as tf 
from tensorflow.initializers import random_uniform

# noise function
class OUActionNoise(object):
    def __init__(self, mu, sigma=0.15, theta=0.2, dt=1e-2, x0=None):
        self.theta = theta
        self.mu = mu
        self.dt = dt
        self.sigma = sigma
        self.x0 = x0
        self.reset()
    
        
    def __call__(self):
        x = self.x_prev + self.theta*(self.mu-self.x_prev)*self.dt +\
            self.sigma*np.sqrt(self.dt)*np.random.normal(size=self.mu.shape)
        self.x_prev = x
        return x
    
    def reset(self):
        self.x_prev = self.x0 if self.x0 is not None else np.zeros_like(self.mu)
        
        
class PeplayBuffer(object):
    def __inti__(self, max_size, input_shape, n_actions):
        self.mem_size = max_size
        self.mem_cntr = 0
        self.state_memory = np.zeros((self.mem_size, *input_shape))
        self.new_state_memory = np.zeros((self.mem_size, *input_shape))
        self.action_memory = np.zeros((self.mem_size, n_actions))
        self.reward_memory = np.zeros(self.mem_size)
        self.terminal_memory = np.zeros(self.mem_size, dtype=np.float32)
        
    def store_transition(self, state, action, reward, state_, done):
        index = self.mem_cntr % self.mem_size
        self.state_memory[index] = state
        self.new_state_memory[index] = state_
        self.reward_memory[index] = reward
        self.action_memory[index] = action
# do not want to count reward after episode is ended
        self.terminal_memory[index] = 1 - int(done)
        self.mem_cntr += 1

# function for sample of buffer and return batch size
        
    def sample_buffer(self, batch_size):
        max_mem = min(self.mem_cntr, self.mem_size)
        batch = np.random.choice(max_mem, batch_size)
        
        states = self.state_memory[batch]
        new_states = self.new_state_memory[batch]
        actions = self.action_memory[batch]
        rewards = self.reward_memory[batch]
        terminal = self.terminal_memory[batch]
        
        return states, actions, rewards, new_states, terminal
    
    
# actor decides which action to take   
class Actor(object):
    def __inti__(self, lr, n_actions, name, input_dims, sess, fc1_dims,
                 fc2_dims, action_bound, batch_size=64, chkpt_dir='tmp/ddpg'):
        self.lr = lr
        self.n_actions = n_actions
        self.name = name
        self.fc1_dims = fc1_dims
        self.fc2_dims = fc2_dims
        self.sess = sess
        self.batch_size = batch_size
        self.action_bound = action_bound
        self.chkpt_dir = chkpt_dir
        self.build_network()
# scope the set of parameter for actor and critic network        
        self.params = tf.trainable_variables(scope=self.name)
        self.checkpoint_file = os.path.join(chkpt_dir, name+'_ddpg.ckpt')
        
# calculate gradiant
        self.unnormalized_actor_gradients = tf.gradients(
            self.mu, self.params, -self.action_gradient)

        self.actor_gradients = list(map(lambda x: tf.div(x, self.batch_size),
                                        self.unnormalized_actor_gradients))

        self.optimize = tf.train.AdamOptimizer(self.lr).\
                    apply_gradients(zip(self.actor_gradients, self.params))
    
    
    def build_network(self):
# every network has its scope
        with tf.variable_scope(self.name):
            self.input = tf.placeholder(tf.float32,
                                        shape=[None, *self.input_dims],
                                        name='inputs')

            self.action_gradient = tf.placeholder(tf.float32,
                                          shape=[None, self.n_actions],
                                          name='gradients')
            # initialization
            f1 = 1. / np.sqrt(self.fc1_dims)
            dense1 = tf.layers.dense(self.input, units=self.fc1_dims,
                                     kernel_initializer=random_uniform(-f1, f1),
                                     bias_initializer=random_uniform(-f1, f1))
            # do batch normalization
            batch1 = tf.layers.batch_normalization(dense1)
            # activate the first layer
            layer1_activation = tf.nn.relu(batch1)
            
            
            f2 = 1. / np.sqrt(self.fc2_dims)
            dense2 = tf.layers.dense(layer1_activation, units=self.fc2_dims,
                                     kernel_initializer=random_uniform(-f2, f2),
                                     bias_initializer=random_uniform(-f2, f2))
            batch2 = tf.layers.batch_normalization(dense2)
            layer2_activation = tf.nn.relu(batch2)
            
            # out put layer which is the deterministic policy
            f3 = 0.003
            mu = tf.layers.dense(layer2_activation, units=self.n_actions,
                            activation='tanh',
                            kernel_initializer= random_uniform(-f3, f3),
                            bias_initializer=random_uniform(-f3, f3))
            self.mu = tf.multiply(mu, self.action_bound)
            
# getting the actual action out of the network
    def predict(self, inputs):
             return self.sess.run(self.mu, feed_dict={self.input: inputs})
# actual backpropogation though the network
    def train(self, inputs, gradients):
        self.sess.run(self.optimize,
                      feed_dict={self.input: inputs,
                                 self.action_gradient: gradients})             
         
# two functiosn for loading and saving the model            
    def load_checkpoint(self):
        print("...Loading checkpoint...")
        self.saver.restore(self.sess, self.checkpoint_file)

    def save_checkpoint(self):
        print("...Saving checkpoint...")
        self.saver.save(self.sess, self.checkpoint_file)
        

class Critic(object):
    def __init__(self, lr, n_actions, name, input_dims, sess, fc1_dims, fc2_dims,
                 batch_size=64, chkpt_dir='tmp/ddpg'):
        self.lr = lr
        self.n_actions = n_actions
        self.name = name
        self.fc1_dims = fc1_dims
        self.fc2_dims = fc2_dims
        self.chkpt_dir = chkpt_dir
        self.input_dims = input_dims
        self.batch_size = batch_size
        self.sess = sess
        self.build_network()
        self.params = tf.trainable_variables(scope=self.name)
        self.saver = tf.train.Saver()
        self.checkpoint_file = os.path.join(chkpt_dir, name +'_ddpg.ckpt')

        self.optimize = tf.train.AdamOptimizer(self.lr).minimize(self.loss)

        self.action_gradients = tf.gradients(self.q, self.actions)
        
            
            
            



    
    
        
        