# -*- coding: utf-8 -*-
"""
Created on Tue Mar 17 17:43:46 2020
Deep Deterministic Policy Gradients Method with Tensorflow

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
        
        
class ReplayBuffer(object):
    def __init__(self, max_size, input_shape, n_actions):
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
    def __init__(self, lr, n_actions, name, input_dims, sess, fc1_dims,
                 fc2_dims, action_bound, batch_size=64, chkpt_dir='tmp/ddpg'):
        self.lr = lr
        self.n_actions = n_actions
        self.input_dims = input_dims
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
        
        # we have a dense layer for input and we want to initialize it with random number
        
    def build_network(self):
        with tf.variable_scope(self.name):
            self.input = tf.placeholder(tf.float32,
                                        shape=[None, *self.input_dims],
                                        name='inputs')

            self.actions = tf.placeholder(tf.float32,
                                          shape=[None, self.n_actions],
                                          name='actions')

            self.q_target = tf.placeholder(tf.float32,
                                           shape=[None,1],
                                           name='targets')

            f1 = 1. / np.sqrt(self.fc1_dims)
            dense1 = tf.layers.dense(self.input, units=self.fc1_dims,
                                     kernel_initializer=random_uniform(-f1, f1),
                                     bias_initializer=random_uniform(-f1, f1))
            batch1 = tf.layers.batch_normalization(dense1)
            layer1_activation = tf.nn.relu(batch1)

        # second layer does not have activation since it needs another layer
            f2 = 1. / np.sqrt(self.fc2_dims)
            dense2 = tf.layers.dense(layer1_activation, units=self.fc2_dims,
                                     kernel_initializer=random_uniform(-f2, f2),
                                     bias_initializer=random_uniform(-f2, f2))
            batch2 = tf.layers.batch_normalization(dense2)

            action_in = tf.layers.dense(self.actions, units=self.fc2_dims,
                                        activation='relu')
            state_actions = tf.add(batch2, action_in)
            state_actions = tf.nn.relu(state_actions)
        # activate state_action
            f3 = 0.003
            self.q = tf.layers.dense(state_actions, units=1,
                               kernel_initializer=random_uniform(-f3, f3),
                               bias_initializer=random_uniform(-f3, f3),
                               kernel_regularizer=tf.keras.regularizers.l2(0.01))
        # loss function and self.q is the out put of deep NN
            self.loss = tf.losses.mean_squared_error(self.q_target, self.q)        
        
        
    def predict(self, inputs, actions):
        return self.sess.run(self.q,
                             feed_dict={self.input: inputs,
                                        self.actions: actions})
    def train(self, inputs, actions, q_target):
        return self.sess.run(self.optimize,
                      feed_dict={self.input: inputs,
                                 self.actions: actions,
                                 self.q_target: q_target})        
        
        
    # function for getting action-gradient 
    def get_action_gradients(self, inputs, actions):
        return self.sess.run(self.action_gradients,
                             feed_dict={self.input: inputs,
                                        self.actions: actions})
    def load_checkpoint(self):
        print("...Loading checkpoint...")
        self.saver.restore(self.sess, self.checkpoint_file)

    def save_checkpoint(self):
        print("...Saving checkpoint...")
        self.saver.save(self.sess, self.checkpoint_file)



# niose, replay buffer, and four different NNs for actor and critic drive for based object of agent      
class Agent(object):
    def __init__(self, alpha, beta, input_dims, tau, env, gamma=0.99, n_actions=2,
                 max_size=1000000, layer1_size=400, layer2_size=300,
                 batch_size=64):
        self.gamma = gamma
        self.tau = tau
        self.memory = ReplayBuffer(max_size, input_dims, n_actions)
        self.batch_size = batch_size
        self.sess = tf.Session()
        
        # four NNs layers
        self.actor = Actor(alpha, n_actions, 'Actor', input_dims, self.sess,
                           layer1_size, layer2_size, env.action_space.high)
        self.critic = Critic(beta, n_actions, 'Critic', input_dims,self.sess,
                             layer1_size, layer2_size)

        self.target_actor = Actor(alpha, n_actions, 'TargetActor',
                                  input_dims, self.sess, layer1_size,
                                  layer2_size, env.action_space.high)
        self.target_critic = Critic(beta, n_actions, 'TargetCritic', input_dims,
                                    self.sess, layer1_size, layer2_size)        
        
        # noise function
        self.noise = OUActionNoise(mu=np.zeros(n_actions))   
        
        # operation to perform the soft update
        # update operation iterate over target critic and actor    
        self.update_critic = \
        [self.target_critic.params[i].assign(
                      tf.multiply(self.critic.params[i], self.tau) \
                    + tf.multiply(self.target_critic.params[i], 1. - self.tau))
         for i in range(len(self.target_critic.params))]

        self.update_actor = \
        [self.target_actor.params[i].assign(
                      tf.multiply(self.actor.params[i], self.tau) \
                    + tf.multiply(self.target_actor.params[i], 1. - self.tau))
         for i in range(len(self.target_actor.params))]
        
        self.sess.run(tf.global_variables_initializer())

        self.update_network_parameters(first=True)
        
    def update_network_parameters(self, first=False):
        if first:
            old_tau = self.tau
            self.tau = 1.0
            self.target_critic.sess.run(self.update_critic)
            self.target_actor.sess.run(self.update_actor)
            self.tau = old_tau
        else:
            self.target_critic.sess.run(self.update_critic)
            self.target_actor.sess.run(self.update_actor)        

   # storing transitions
    def remember(self, state, action, reward, new_state, done):
        self.memory.store_transition(state, action, reward, new_state, done)
   
   # choose action with state as an input

    def choose_action(self, state):
        state = state[np.newaxis, :]
        mu = self.actor.predict(state) # returns list of list
        noise = self.noise()
        mu_prime = mu + noise

        return mu_prime[0]  
    
    
    
    def learn(self):
        if self.memory.mem_cntr < self.batch_size:
            return
        state, action, reward, new_state, done = \
                                      self.memory.sample_buffer(self.batch_size)
                                      
        # do update, pass state and action through all four networks
        critic_value_ = self.target_critic.predict(new_state,
                                           self.target_actor.predict(new_state))
        target = []
        for j in range(self.batch_size):
            target.append(reward[j] + self.gamma*critic_value_[j]*done[j])
        target = np.reshape(target, (self.batch_size, 1))

        _ = self.critic.train(state, action, target)

        # actor update
        a_outs = self.actor.predict(state)
        # gradient of critic with respect to the action is taken
        grads = self.critic.get_action_gradients(state, a_outs)

        self.actor.train(state, grads[0])

        self.update_network_parameters()

    def save_models(self):
        self.actor.save_checkpoint()
        self.target_actor.save_checkpoint()
        self.critic.save_checkpoint()
        self.target_critic.save_checkpoint()

    def load_models(self):
        self.actor.load_checkpoint()
        self.target_actor.load_checkpoint()
        self.critic.save_checkpoint()
        self.target_critic.save_checkpoint()        
